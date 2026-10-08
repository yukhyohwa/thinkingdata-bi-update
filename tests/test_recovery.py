import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.core.engines.ta_engine import ThinkingDataEngine


class RecoveryTests(unittest.TestCase):
    def engine(self):
        config = SimpleNamespace(url='https://example.com', user='user', password='password')
        return ThinkingDataEngine(config, 'https://example.com/#/ide/1', 'unused-test-session')

    def test_retry_exits_playwright_before_starting_another_context(self):
        engine = self.engine()
        depth = 0
        depths = []

        class Context:
            def __enter__(self):
                nonlocal depth
                depth += 1
                depths.append(depth)
                return SimpleNamespace(chromium=None)

            def __exit__(self, *args):
                nonlocal depth
                depth -= 1

        with patch('src.core.engines.ta_engine.sync_playwright', side_effect=Context), \
             patch.object(engine, '_launch', side_effect=[RuntimeError('launch failed'), ValueError('second attempt')]), \
             patch.object(engine, '_clear_session') as clear:
            with self.assertRaisesRegex(ValueError, 'second attempt'):
                engine.save_report('SELECT 1')
            clear.assert_called_once()
        self.assertEqual(depths, [1, 1])

    def test_unready_page_is_not_treated_as_valid_login(self):
        page = Mock()
        page.wait_for_selector.side_effect = TimeoutError('not loaded')
        page.get_by_text.return_value.count.return_value = 0
        page.locator.return_value.inner_text.return_value = '加载中'
        page.url = 'https://example.com/#/ide/1'
        page.frames = []
        with self.assertRaisesRegex(RuntimeError, 'Neither SQL editor nor login'):
            ThinkingDataEngine._wait_for_login_or_ide(page, timeout=1)

    def test_invalid_chart_is_not_saved(self):
        engine = self.engine()
        page = Mock()
        dialog = page.locator.return_value.last
        dialog.inner_text.return_value = '图表未正常展示，确认保存报表吗？'
        with self.assertRaisesRegex(RuntimeError, 'Chart bindings are invalid'):
            engine._confirm_update_dialog(page)
        dialog.locator.assert_not_called()

    def test_automatic_login_can_remain_in_background(self):
        engine = self.engine()
        context = Mock()
        context.__enter__ = Mock(return_value=SimpleNamespace(chromium=None))
        context.__exit__ = Mock(return_value=False)
        with patch('src.core.engines.ta_engine.sync_playwright', return_value=context), \
             patch.object(engine, '_launch', side_effect=RuntimeError('stop')) as launch:
            with self.assertRaisesRegex(RuntimeError, 'stop'):
                engine.login(retried=True, show_window=False)
            self.assertFalse(launch.call_args.kwargs['show_window'])


if __name__ == '__main__':
    unittest.main()
