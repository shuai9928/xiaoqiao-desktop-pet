# 素材与授权说明

源码的 MIT 许可不覆盖第三方美术、角色、音乐和语音。

| 素材 | 来源及分发说明 |
| --- | --- |
| `assets/main.png`、`main.jpg`、`decor_*.png`、`expr/*.png` | 原项目提供的角色立绘与贴纸。维护者于 2026-09-13 确认拥有随本项目公开分发的授权。版权归各自权利人；本仓库不额外授予素材商用、修改或再次分发许可。 |
| `assets/song.mp3` | 原项目提供的歌曲，维护者确认可随本项目公开分发。版权归权利人；不适用源码 MIT 许可。 |
| `assets/audio/` 的角色语音 | 使用 Microsoft Edge 的 zh-CN-XiaoxiaoNeural 语音预渲染。原始来源记录见下方链接；维护者确认可随本仓库公开分发，不据此推定微软服务输出普遍具有开源许可。 |
| `assets/audio/magic_1.wav` 至 `magic_6.wav` | 原来源记录：JaggedStone 的 [Magic Spell SFX](https://opengameart.org/content/magic-spell-sfx)，CC0；从原音频转换为 WAV。 |

音频原始记录见 [assets/audio/CREDITS.md](assets/audio/CREDITS.md)。其中“仅在本机自用”属于早期制作记录；本次公开分发依据维护者另行确认的授权，未将其扩展为对所有使用者的素材再授权。

若要单独使用、修改、商用或再次分发第三方素材，请自行核实对应授权范围。也可替换为自己有权使用的素材；角色形状变化较大时，需要同步调整 `assets/config.json` 中的五官位置和 `depth_model.py` 中的部位权重。

如发现署名或授权记录需要更正，请联系仓库维护者。请勿在 Issue 中上传私人授权文件、身份证明或合同原件。
