# H10 研究报告 v01（2026-08-14，描述性，无调参）

输入：frozen episodes（SHA 66d5943f...，成交子集 n=9,625）。脚本：
research/factor-lab/h10_quality_robustness_v01.py；输出：
research/factor-lab/runs/h10-v01/h10-v01.json。

## 总体 win share（成交子集口径）

| 组 | n | win share |
| --- | --- | --- |
| 全部 | 9,625 | 24.2% |
| setup_quality>=80 | 1,227 | 28.3%（+4.1pp） |
| entry_quality>=80 | 556 | **10.1%（−14.1pp）** |

## 按信号时点分层的 setup>=80 效应

| 时点桶 | 全部 win | setup>=80 win | 增量 |
| --- | --- | --- | --- |
| T+1-2 | 10.2% | 14.6% | **+4.4pp** |
| T+3 | 45.6% | 61.7% | **+16.1pp** |
| T+4-5 | 65.5% | 67.2% | +1.7pp |
| T+6-10 | 72.1% | 70.1% | −2.0pp |

## 结论

- **setup_quality>=80 的正效应在时点分层内方向一致且集中于 T+3（+16pp）**，
  T+1-2 仍有 +4.4pp；T+4 之后消失（基线胜率已高，天花板效应）。
  状态：OBSERVE_ONLY（分层内稳健，未做 forward）。
- **entry_quality>=80 在 win-share 口径下为负（10.1% vs 24.2%）**——与冻结
  基线 E[R] 口径（entry>=80 为正）方向不一致。解释：entry_quality 的效应
  是**赔率型**（低胜率、高赔率/大 R），不是胜率型；win share 无法复现
  E[R] 结论。**口径警示**：H10 必须以 R/E[R] 口径复算才能与冻结基线对齐。
  状态：OBSERVE_ONLY（口径存疑，待 R 口径复算）。

## 对架构的启示

- 研究层报告必须同时给出 win share 与 E[R] 双口径，避免「赔率型因子被
  胜率口径误杀」或反之；
- H10 的 R 口径复算列入待办（复用 execution_reality 的输出框架）。
