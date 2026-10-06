# 发布副本检查（2026-10-06 CST）

环境：Windows 原生 Python 3.14.4；独立副本，无个人设置、会话或 AI 密钥。
- test_pet.py：177/177。
- unittest test_life test_swing test_session_lights test_ai_lights_data test_hat_fx test_action_fx test_core_profile：192 项，OK，2 跳过。
- tools/check_public_files.py：零发现（上传前再次检查）。
- tools/check_docs.py：24 篇根目录/docs/tools文档、87 个本地引用，零发现。
- tools/run_checks.py --unit-only：136 项，1 失败、2 跳过（即133通过）。
  失败：test_recovery.DeferredFxTests.test_defer_builds_later_and_draws_nothing_until_then，
  test_recovery.py:281，实际 30、期望 20。
  旧断言使用 2 * HIT_STEPS；B5 加入 mint 档后出现第三种配色。
  此为本次发布发现的已有实现/测试口径不一致，未修改测试或特效逻辑来掩盖失败。
  运行器在此失败后停止，后续 test_agent.py 未运行。
- 原 GitHub Windows CI 保留，预期会报告上述失败；本分支为继续开发交接，不是全绿发布版。
- 历史 test_core_runtime 额度连接失败未在本次七套定向测试覆盖；见旧交接记录。
- 没有重新测量性能、实时桌面效果或重新启动主桌宠。

发布前测试假密钥改为运行时生成的占位输入，test_ai_lights_data 重跑24项通过。
