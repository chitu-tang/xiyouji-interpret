# 《西游记》原文片段逐段深读与口播 Skill

v3.2。面向已贴出的《西游记》原文片段：以所贴原文为核心锚点，兼容极简前情交代与传统文化干货延展（借西游讲透道家/佛学/历史/名物，最后收回到人物与叙事追问），经两道人工关口（选点 + 确认框架）产出 **1000–1200 字**可直接念出的口播稿，再通过三审三校与 Python 机械校验确保引文逐字保真、自然聊天质感、有主轴有边界。

## 它做什么（三种模式 × 两种体裁）

| 你说 | 运行模式 | 它做什么 |
|---|---|---|
| 帮我解读 / 逐段分析 / 深度解读 / 写成口播稿 | **P 管线模式（默认）** | `P0 核验 → P1 出 2-6 候选卡 → ✋等你选 → P3 定向研究 → P4 出框架 → ✋等你确认 → P5 成稿(1000-1200字口播) → P6 机械校验+三审 → P7 交付` |
| 贴原文 + 已指定某个角度 | **P 管线（跳过扫点）** | 先做 `P0 核验`，再跳过 P1–P2 直接进入 P3 研究与 P4 框架确认 |
| 值不值得讲 / 有哪些角度 / 怎么解 | **B 仅候选卡** | 只做到 P1 交候选卡；选完未说成稿则交写作 Brief |
| 直接写 / 不用给我选 / 一口气出稿 | **A 直出模式** | 跳过 P2 和 P4 两个等待点直接交付（仍遵守范围锁、边界校准与机械校验） |
| 第 X 回 / 这一回拆几篇 / 5000–7000 字长文 | **转交长文管线** | 转交 [xiyouji-chapter-longform](https://github.com/chitu-tang/xiyouji-deep-read)，本 Skill 不硬接 |

- **默认体裁**：直接能念的**口播稿**（钩子 → 固定开场白 → 自然推进正文 → 画面收束 → 固定结束语），核验、边界、三审与研究说明附在稿外，不混入正文。
- **可选体裁**：明确说“写成文章 / 结构化深读文 / 不要口播包装”时切换为结构化深读文模板。

## 核心纪律

1. **范围锁**：用户提供的这段原文是唯一文本证据。不引用紧邻上下文或后文当论据，外部材料只解释原文里已出现的内容，需要后文才成立的角度不进候选。
2. **机械引文保真**：所有直接引文必须逐字命中用户原文，节引按句读单位在截断端标省略号，非原文（概念标签、标题、概括等）严禁加任何成对引号。
3. **防现代化误读**：人物言行亮点必查当代观念代入风险；凡禁止型边界，除稿外立条外，正文须用陈述式点破并就地拒绝。
4. **反 AI 味硬指标**：正文本体（不含引文）否定对照句式每千字 **0–1 处**、`但/但是` 每千字最多 1 处、破折号 ≤ 2、冒号 ≤ 3、感叹号 ≤ 1、零禁用短语。

## 确定性校验脚本

仓库自带零外部依赖的 Python 3 校验脚本（与 `xiyouji-deep-read` 同源采用 Unicode `U+4E00-U+9FFF` 汉字计数口径）：

```bash
# 校验一份口播交付稿（默认 1000-1200 汉字、全交付物扫引号）
python3 scripts/verify_draft.py \
  --source path/to/source.txt \
  --draft path/to/deliverable.md \
  --genre spoken \
  --min-hanzi 1000 \
  --max-hanzi 1200

# 运行脚本自身单元测试
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

## 目录结构

```text
xiyouji-interpret/
├── SKILL.md                           # 主规范（单源真理：分流、范围锁、P0-P7、11 道质量门）
├── README.md                          # 使用说明与安装指南
├── history.md                         # 已讲台账（P1 去重读取；P7 经确认后追加）
├── scripts/
│   ├── verify_draft.py                # 确定性机械校验（字数、引文/范围锁、禁用项、标点、口播结构）
│   └── test_verify_draft.py           # 校验脚本单元测试
├── references/
│   ├── quote-and-scope.md             # 范围锁、版本核验、引文/节引算法与防现代化误读细则
│   ├── angle-checklist.md             # 文本问题发现与证据门清单
│   ├── output-template.md             # 交付模板（模板一：口播稿默认；模板二：深读文可选）
│   ├── style-guide.md                 # 口播语感、结构驱动与节奏指南
│   ├── forbidden.md                   # 禁用短语与限频硬规则（含否定对照 0-1 处/千字）
│   └── ai-pattern-checklist.md        # AI 写作痕迹检查清单（口播适配版）
├── examples/
│   ├── gold-01-石猴应声进洞-端到端标杆.md  # 通过机械校验与全部 11 门的端到端标杆
│   └── voice-samples/                 # v1 口播语感参考样本（仅学语感，不抄越界写法）
└── docs/
    └── evaluation.md                  # 维护者回归测试规范、公开评分 Rubric 与红线标准
```

## 与完整回目长文 Skill 的分工

本仓库的 frontmatter `name` 保持为 `xiyouji-excerpt-angle-planner`，与完整回目长文仓库 [xiyouji-deep-read](https://github.com/chitu-tang/xiyouji-deep-read)（`name: xiyouji-chapter-longform`）双向互指、严禁混用：

- **本 Skill（片段 · 口播）**：处理你贴出的单段原文，输出 1000–1200 字口播稿或候选角度卡；
- **`xiyouji-chapter-longform`（回目 · 长文）**：处理完整单回底本核验、拆篇、5000–7000 字长文写作、审核与不可变归档。

## 安装使用

将本仓库克隆至你所用 Agent 工具的 Skills 目录即可自动发现：

- **Antigravity**：`<workspace>/.agents/skills/xiyouji-interpret` 或 `~/.gemini/config/skills/xiyouji-interpret`
- **Claude Code / 通用 Agent Skills**：`~/.claude/skills/xiyouji-interpret` 或项目内 `.claude/skills/xiyouji-interpret`
