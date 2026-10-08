import os
import re
import shutil
import stat
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.core.engines.base_engine import BaseEngine
from src.utils.logger import logger


class _BrowserLaunchFailed(Exception):
    pass


class _NeedsFreshLogin(Exception):
    pass


class ThinkingDataEngine(BaseEngine):
    """ThinkingData web automation for recalculating and updating an existing report."""

    def __init__(self, config, sql_url: str, session_dir: str):
        self.config = config
        self.base_url = config.url or self._origin(sql_url)
        self.sql_url = sql_url
        self.username = config.user
        self.password = config.password
        self.user_data_dir = session_dir

    @staticmethod
    def _origin(url: str) -> str:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}/"

    def _context_options(self, show_window: bool):
        return {
            "headless": False,  # The ThinkingData IDE requires a real browser renderer.
            "slow_mo": 100,
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--window-size=1920,1080",
                "--window-position=0,0" if show_window else "--window-position=-10000,-10000",
            ],
            "permissions": ["clipboard-read", "clipboard-write"],
        }

    def _launch(self, chromium, show_window: bool):
        os.makedirs(self.user_data_dir, exist_ok=True)
        return chromium.launch_persistent_context(self.user_data_dir, **self._context_options(show_window))

    def _clear_session(self):
        def onerror(func, path, _exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        if os.path.isdir(self.user_data_dir):
            shutil.rmtree(self.user_data_dir, onerror=onerror)
        os.makedirs(self.user_data_dir, exist_ok=True)
        logger.info("Expired session cleared; creating a fresh session.")

    @staticmethod
    def _click(page, locator):
        try:
            # Use a trusted Playwright click first. The ThinkingData login form
            # ignores some synthetic JS click events.
            locator.click(timeout=10000)
        except Exception:
            try:
                locator.click(force=True, timeout=10000)
            except Exception:
                locator.evaluate("el => el.click()")

    def _is_login_page(self, page) -> bool:
        return "login" in page.url.lower() or bool(page.query_selector('input[type="password"]'))

    @staticmethod
    def _wait_for_login_or_ide(page, timeout: int = 60000):
        """Wait for an actual authenticated IDE or a login form after SPA navigation."""
        try:
            page.wait_for_selector(
                '.monaco-editor, .CodeMirror, .ace_editor, .tant-monaco-editor, input[type="password"]',
                timeout=timeout,
            )
        except Exception:
            hint = page.get_by_text(re.compile('^(我知道了|已知晓)$'))
            if hint.count() and hint.first.is_visible():
                hint.first.click()
                logger.info("Dismissed first-use navigation hint.")
                try:
                    page.wait_for_selector(
                        '.monaco-editor, .CodeMirror, .ace_editor, .tant-monaco-editor, input[type="password"]',
                        timeout=timeout,
                    )
                    return
                except Exception:
                    pass
            logger.warning("Editor/login did not become ready. URL: %s", page.url)
            logger.warning("Page title: %s", page.title())
            logger.warning("Visible page state: %s", page.locator('body').inner_text(timeout=3000)[:4000])
            logger.warning("Frames: %s", [frame.url for frame in page.frames])
            raise RuntimeError('Neither SQL editor nor login form became ready; refusing to treat the URL as a valid session.')

    def _perform_login_logic(self, page):
        user_input = page.wait_for_selector(
            'input[placeholder*="Account"], input[placeholder*="Username"], input[placeholder*="账号"], input[id="username"], input[type="text"]',
            timeout=15000,
        )
        password_input = page.wait_for_selector(
            'input[placeholder*="Password"], input[placeholder*="密码"], input[id="password"], input[type="password"]',
            timeout=15000,
        )
        user_input.fill("")
        user_input.type(self.username, delay=30)
        password_input.fill("")
        password_input.type(self.password, delay=30)
        try:
            checkbox = page.query_selector('input[type="checkbox"]')
            if checkbox and not checkbox.is_checked():
                checkbox.check()
        except Exception:
            pass
        # The current OAuth page's primary login control is an icon-only button:
        # <button class="... loginBtn... loginBtnPrimary...">. It has no text.
        button = page.locator(
            'button[class*="loginBtn"], input[type="submit"], '
            'button:has-text("登录"), button:has-text("Login"), button[type="submit"], .ant-btn-primary'
        ).first
        logger.info("Account and password filled; clicking the login button…")
        self._click(page, button)
        page.wait_for_timeout(5000)

    def login(self, retried: bool = False, show_window: bool = True):
        """Establish the persistent session, keeping automatic recovery in background."""
        try:
            with sync_playwright() as playwright:
                context = self._launch(playwright.chromium, show_window=show_window)
                try:
                    page = context.new_page()
                    # Validate the exact report IDE URL, not only the product home page.
                    # A home-page cookie can exist while the SQL IDE session has expired.
                    page.goto(self.sql_url, timeout=90000, wait_until="commit")
                    self._wait_for_login_or_ide(page)
                    if self._is_login_page(page):
                        logger.info("Logging in to ThinkingData…")
                        self._perform_login_logic(page)
                        page.goto(self.sql_url, timeout=90000, wait_until="commit")
                        self._wait_for_login_or_ide(page)
                    if self._is_login_page(page):
                        raise RuntimeError("ThinkingData still requires login after automatic sign-in.")
                    else:
                        if page.url != self.sql_url:
                            logger.info("Login redirected elsewhere; reopening the SQL comment URL…")
                            page.goto(self.sql_url, timeout=90000, wait_until="commit")
                            self._wait_for_login_or_ide(page)
                        if page.url != self.sql_url:
                            raise RuntimeError(
                                f"ThinkingData did not stay on the requested SQL URL. Current URL: {page.url}"
                            )
                        # Give the SPA time to render the selected report panel before closing.
                        page.wait_for_timeout(3000)
                        logger.info("Report IDE session is valid. Final URL: %s", page.url)
                    logger.info("Session saved in %s.", self.user_data_dir)
                finally:
                    context.close()
        except Exception as exc:
            if retried:
                raise
            logger.warning("Saved session could not launch: %s", exc)
            self._clear_session()
            logger.info("Retrying the browser launch once with a fresh session.")
            return self.login(retried=True, show_window=show_window)

    def fetch(self, sql: str, **kwargs):
        return self.save_report(sql, show_window=kwargs.get("show_window", False))

    def inspect_report(self, output_dir: str, panel_url: str | None = None):
        """Read saved SQL and visible report state without changing the report."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            context = self._launch(playwright.chromium, False)
            try:
                page = context.new_page()
                page.goto(self.sql_url, timeout=90000, wait_until="commit")
                self._wait_for_login_or_ide(page, timeout=60000)
                if self._is_login_page(page):
                    raise RuntimeError("Inspection needs an authenticated report session.")
                editor = page.wait_for_selector('.monaco-editor, .CodeMirror, .ace_editor, textarea, .tant-monaco-editor', timeout=60000)
                self._click(page, editor)
                page.keyboard.press('Control+A')
                page.keyboard.press('Control+C')
                sql = page.evaluate('() => navigator.clipboard.readText()')
                if not re.search(r'\bSELECT\b', sql, re.IGNORECASE):
                    raise RuntimeError('Editor copy did not return SQL.')
                (out / 'remote.sql').write_text(sql, encoding='utf-8')
                (out / 'page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                page.screenshot(path=str(out / 'page.png'), full_page=True)
                if panel_url:
                    from urllib.parse import urlsplit
                    if urlsplit(panel_url).netloc != urlsplit(self.sql_url).netloc:
                        raise ValueError('Panel inspection must use the same ThinkingData host.')
                    page.goto(panel_url, timeout=90000, wait_until='commit')
                    page.get_by_text('KPI预估与达成', exact=True).first.wait_for(state='visible', timeout=60000)
                    # Dashboard charts can draw date labels on canvas rather than DOM text.
                    page.wait_for_timeout(3000)
                    (out / 'panel.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                    page.screenshot(path=str(out / 'panel.png'), full_page=True)
                logger.info('Read-only report snapshot saved to %s', out)
            finally:
                context.close()

    def _replace_sql_by_paste(self, page, sql_text: str):
        """Use the editor's native select-all/paste flow so saved custom parameters stay intact."""
        clipboard_ready = False
        # Copy local SQL first, before focusing or selecting anything in the web editor.
        try:
            page.evaluate("text => navigator.clipboard.writeText(text)", sql_text)
            clipboard_ready = True
            logger.info("Local SQL copied to the browser clipboard.")
        except Exception:
            logger.warning("Browser clipboard is unavailable; will use editor text insertion as fallback.")

        editor = page.wait_for_selector(
            ".monaco-editor, .CodeMirror, .ace_editor, textarea, .tant-monaco-editor",
            timeout=30000,
        )
        self._click(page, editor)
        page.keyboard.press("Control+A")
        logger.info("Existing web SQL selected with Ctrl+A.")
        # Deliberately paste over the selection instead of resetting Monaco's model.
        if clipboard_ready:
            page.keyboard.press("Control+V")
        else:
            # This still replaces the selection without changing the saved parameter controls.
            page.keyboard.insert_text(sql_text)
        logger.info("Local SQL pasted over the selected web SQL; report parameters were preserved.")
        page.wait_for_timeout(1000)

    @staticmethod
    def _first_visible(page, selectors):
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.is_visible() and locator.is_enabled():
                    return locator
            except Exception:
                continue
        return None

    def _confirm_update_dialog(self, page):
        """Click the exact 更新 / Update action inside the confirmation dialog."""
        logger.info("Waiting for the update confirmation dialog…")
        dialog = page.locator(
            '.ant-modal:visible, .ant-modal-content:visible, [role="dialog"]:visible'
        ).last
        dialog.wait_for(state="visible", timeout=15000)

        if '图表未正常展示' in dialog.inner_text():
            raise RuntimeError('Chart bindings are invalid; preserve the saved report column aliases before updating.')

        buttons = dialog.locator('button, [role="button"]')
        confirm = None
        for index in range(buttons.count()):
            candidate = buttons.nth(index)
            try:
                label = re.sub(r"\s+", " ", candidate.inner_text()).strip()
                if label in {"更新", "Update"} and candidate.is_visible() and candidate.is_enabled():
                    confirm = candidate
                    break
            except Exception:
                continue
        # Some TA builds render the primary modal action without accessible text.
        if confirm is None:
            for selector in (
                '.ant-modal-footer button.ant-btn-primary',
                '.ant-modal-footer button[class*="primary"]',
                '.ant-modal-footer button:last-child',
                'button.ant-btn-primary',
            ):
                candidate = dialog.locator(selector).last
                try:
                    if candidate.is_visible() and candidate.is_enabled():
                        confirm = candidate
                        break
                except Exception:
                    continue
        if confirm is None:
            logger.warning("Update dialog text: %s", dialog.inner_text())
            raise RuntimeError("Update confirmation dialog appeared, but its 更新 / Update button was not found.")

        logger.info("Confirmation dialog opened; clicking its 更新 / Update button.")
        self._click(page, confirm)
        dialog.wait_for(state="hidden", timeout=30000)
        logger.info("Confirmation dialog closed after update confirmation.")

    def save_report(self, sql_text: str, show_window: bool = False, retried: bool = False):
        """Paste SQL, calculate it, then click 更新报表 / Update Report. Never downloads data."""
        try:
            with sync_playwright() as playwright:
                try:
                    context = self._launch(playwright.chromium, show_window)
                except Exception as exc:
                    if retried:
                        raise
                    logger.warning("Saved session could not launch: %s", exc)
                    raise _BrowserLaunchFailed() from exc
                try:
                    page = context.new_page()
                    logger.info("Opening report SQL URL: %s", self.sql_url)
                    # ThinkingData is a long-polling SPA, so networkidle may never occur.
                    # Continue as soon as navigation commits, then wait for the real editor/login UI.
                    page.goto(self.sql_url, timeout=90000, wait_until="commit")
                    self._wait_for_login_or_ide(page)
                    if self._is_login_page(page):
                        if retried:
                            self._perform_login_logic(page)
                        else:
                            raise _NeedsFreshLogin()

                    self._replace_sql_by_paste(page, sql_text)
                    calculate = self._first_visible(page, [
                        'button:has-text("Calculate")', 'button:has-text("计算")', '.ant-btn:has-text("计算")',
                    ])
                    if calculate:
                        logger.info("Calculating report…")
                        self._click(page, calculate)
                    else:
                        logger.info("Calculate button not found; using Ctrl+Enter.")
                        page.keyboard.press("Control+Enter")

                    started = time.time()
                    while time.time() - started < 3600:
                        # 全量下载 / Download All is used only as the completion signal.
                        # It is never clicked by this project.
                        calculation_complete = self._first_visible(page, [
                            'button:has-text("全量下载")', 'button:has-text("Download All")',
                            '[role="button"]:has-text("全量下载")', '[role="button"]:has-text("Download All")',
                        ])
                        if calculation_complete:
                            update = self._first_visible(page, [
                                'button:has-text("更新报表")', '[role="button"]:has-text("更新报表")',
                                'button:has-text("Update Report")', '[role="button"]:has-text("Update Report")',
                                'button:has-text("保存报表")', '[role="button"]:has-text("保存报表")',
                                'button:has-text("Save Report")', '[role="button"]:has-text("Save Report")',
                            ])
                            if update:
                                logger.info("Calculation complete; clicking 更新报表 / Update Report.")
                                self._click(page, update)
                                self._confirm_update_dialog(page)
                                logger.info("Report updated successfully.")
                                return {"status": "updated", "url": self.sql_url}

                        status = page.locator('.ant-tabs-tabpane-active, .ide-results-area').first
                        try:
                            status_text = status.inner_text(timeout=1000)
                        except Exception:
                            status_text = ""
                        if any(token.lower() in status_text.lower() for token in (
                            "java.sql.sqlexception", "parse exception", "mismatched input", "cannot be resolved",
                        )):
                            raise RuntimeError(f"SQL failed: {status_text.strip()}")
                        if int(time.time() - started) % 30 == 0:
                            logger.info("Still waiting for calculation to finish…")
                        page.wait_for_timeout(2000)
                    raise TimeoutError("Calculation did not finish within 60 minutes.")
                finally:
                    context.close()
        except _BrowserLaunchFailed:
            # Retry only after sync_playwright has exited; nesting it creates an asyncio error.
            self._clear_session()
            return self.save_report(sql_text, show_window, retried=True)
        except _NeedsFreshLogin:
            logger.info("Session expired; logging in again.")
            self._clear_session()
            self.login(show_window=show_window)
            return self.save_report(sql_text, show_window, retried=True)
