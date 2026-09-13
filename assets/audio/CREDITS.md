# assets/audio 音效来源与许可证

当前结构:**角色反馈全部是小乔自己的甜妹语音**(Microsoft Edge 在线语音
zh-CN-XiaoxiaoNeural「晓晓」,音高 +20~38Hz 微调),只有施法时垫底的
魔法闪烁是 CC0 音效。全部为本地 WAV(44.1kHz/16bit/单声道),运行时
**离线播放**,与网络无关。

## 1. 小乔的语音(voice_* / greet / bye / pop / notify / tick / levelup /
   sleep / wake / boing / sparkle 共 42 个)
- 来源:由 `_sfx_dl/gen_voice_tts.py` 和 `gen_voice_tts_more.py` 调用
  Microsoft Edge 免费在线语音 **zh-CN-XiaoxiaoNeural(晓晓)** 预渲染,
  内容为短促可爱台词("嘿嘿~""你来啦~""叮咚~""哎哟!"等)。
- 许可证:微软官方语音服务的免费输出,仅在本机渲染成音频文件自用,
  不调用在线接口、不随二次分发牟利。
- 重新生成/改台词:编辑两个脚本里的 CLIPS 表后用系统 Python 重跑,
  文件名不变、代码零改动;`gen_voice.py` 是备用的自制合成"咕咕语"
  生成器(无任何第三方版权),想换回去随时可跑。

## 2. 魔法闪烁(magic_1~6.wav,施法语音的背景层)
- 来源:Magic Spell SFX — OpenGameArt.org(作者 JaggedStone)
  https://opengameart.org/content/magic-spell-sfx
- 许可证:CC0(公有领域,无需署名)
- 文件:magical_1/2/3/5/6/7.ogg → magic_1~6.wav

## 与行为的对应关系(pet.py 内 SFX_FILES 映射)
| 音效 | 触发行为 |
|---|---|
| voice_happy「嘿嘿~」 | 摸头、滚轮顺毛害羞 |
| voice_giggle「嘻嘻嘻~」 | 挠痒、持续滑动顺毛 |
| voice_magic「魔法发动!」+ magic 闪烁 | 双击时间魔法 |
| voice_play「一起跳舞吧!」 | 跳舞 |
| voice_yum「唔,好甜~」 | 吃星光糖果 |
| voice_surprise「哇,飞起来啦!」 | 被抛掷 |
| boing「哎哟!/呜哇!/晕乎乎~」 | 撞墙弹地、被摇晕 |
| sparkle「接住星星~」等 | 撒星星、中键星星爆发 |
| sleep「哈————啊……晚安~」/ wake「呼啊!睡醒了~」 | 入睡 / 醒来 |
| levelup「耶!升级啦~」等 | 好感度升级、猜拳获胜 |
| greet「你来啦~」等 | 鼠标靠近、启动、时段问候 |
| bye「拜拜~」等 | 鼠标离开 |
| pop「来聊天吧~」 | 打开聊天窗 |
| notify「叮咚~」 | 提醒到点 |
| tick「锵~」 | 报时 |

(原有唱歌功能 assets/song.mp3 不在本目录,保持不变。)
