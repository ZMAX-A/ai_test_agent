import unittest

from runner.collaborative_runner_v4 import filter_login_setup_trace


class CollaborativeCompilerTests(unittest.TestCase):
    def test_login_precondition_removes_login_setup_steps(self):
        trace = [
            {"goal": "打开登录页面"},
            {"goal": "在用户名输入框输入账号"},
            {"goal": "输入密码"},
            {"goal": "点击登录按钮"},
            {"goal": "进入顾客档案 /customer"},
        ]
        filtered = filter_login_setup_trace(trace, "需配置 .env 登录凭证")
        self.assertEqual(filtered, [{"goal": "进入顾客档案 /customer"}])

    def test_without_login_precondition_keeps_trace(self):
        trace = [{"goal": "点击登录按钮"}, {"goal": "进入首页"}]
        self.assertEqual(filter_login_setup_trace(trace, ""), trace)


if __name__ == "__main__":
    unittest.main()
