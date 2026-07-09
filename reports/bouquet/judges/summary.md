# BOUQUET multi-judge re-scoring — summary

Generated 2026-07-09T14:11:50.665209+00:00 by `scripts/bouquet_judge_rerun.py stats`.

Per (judge × system × criterion): mean score, tie-rate (share of scores in {9,10}), paragraph-level Spearman rho vs vendored MetricX-ref / MetricX-QE / COMET (`n` = paired non-null paragraphs).

| Judge | System | Criterion | N | Mean | Tie% 9-10 | ρ MetricX-ref | ρ MetricX-QE | ρ COMET |
|---|---|---|---|---|---|---|---|---|
| claude-opus-4.8 | Qwen3.6-27B | accuracy | 198 | 9.293 | 91.9% | -0.0193 (n=198) | +0.0668 (n=198) | +0.1694 (n=198) |
| claude-opus-4.8 | Qwen3.6-27B | fluency | 198 | 9.768 | 98.0% | -0.0295 (n=198) | -0.1114 (n=198) | -0.0101 (n=198) |
| claude-opus-4.8 | Qwen3.6-27B | style | 198 | 8.732 | 69.7% | -0.0552 (n=198) | +0.1142 (n=198) | +0.2244 (n=198) |
| claude-opus-4.8 | Qwen3.6-27B Refined | accuracy | 198 | 9.384 | 93.9% | -0.0195 (n=198) | +0.0425 (n=198) | +0.2448 (n=198) |
| claude-opus-4.8 | Qwen3.6-27B Refined | fluency | 198 | 9.752 | 99.0% | -0.0261 (n=198) | +0.0427 (n=198) | -0.0020 (n=198) |
| claude-opus-4.8 | Qwen3.6-27B Refined | style | 198 | 8.732 | 71.7% | -0.1523 (n=198) | +0.0113 (n=198) | +0.2170 (n=198) |
| claude-opus-4.8 | Translate Gemma | accuracy | 198 | 9.323 | 92.4% | -0.1759 (n=198) | -0.0228 (n=198) | +0.2234 (n=198) |
| claude-opus-4.8 | Translate Gemma | fluency | 198 | 9.657 | 98.0% | -0.1605 (n=198) | -0.0984 (n=198) | +0.2245 (n=198) |
| claude-opus-4.8 | Translate Gemma | style | 198 | 8.813 | 75.2% | -0.1473 (n=198) | -0.0991 (n=198) | +0.2579 (n=198) |
| claude-opus-4.8 | Translate Gemma Refined | accuracy | 198 | 9.444 | 95.0% | -0.1051 (n=198) | -0.0232 (n=198) | +0.1199 (n=198) |
| claude-opus-4.8 | Translate Gemma Refined | fluency | 198 | 9.646 | 97.0% | -0.1222 (n=198) | -0.0120 (n=198) | +0.1448 (n=198) |
| claude-opus-4.8 | Translate Gemma Refined | style | 198 | 8.909 | 83.3% | -0.1588 (n=198) | -0.1095 (n=198) | +0.2038 (n=198) |
| deepseek-v4-flash | Qwen3.6-27B | accuracy | 30 | 9.100 | 76.7% | +0.1096 (n=30) | +0.1108 (n=30) | +0.0536 (n=30) |
| deepseek-v4-flash | Qwen3.6-27B | fluency | 29 | 10.000 | 100.0% | n/a (n=29) | n/a (n=29) | n/a (n=29) |
| deepseek-v4-flash | Qwen3.6-27B | style | 28 | 8.393 | 53.6% | +0.1235 (n=28) | +0.1481 (n=28) | +0.1922 (n=28) |
| deepseek-v4-flash | Qwen3.6-27B Refined | accuracy | 24 | 9.458 | 87.5% | +0.2897 (n=24) | +0.2033 (n=24) | -0.0454 (n=24) |
| deepseek-v4-flash | Qwen3.6-27B Refined | fluency | 24 | 9.875 | 95.8% | +0.0816 (n=24) | +0.1351 (n=24) | -0.1460 (n=24) |
| deepseek-v4-flash | Qwen3.6-27B Refined | style | 23 | 8.609 | 52.2% | -0.0133 (n=23) | +0.2706 (n=23) | +0.1121 (n=23) |
| deepseek-v4-flash | Translate Gemma | accuracy | 23 | 9.522 | 91.3% | -0.3116 (n=23) | -0.1652 (n=23) | +0.3798 (n=23) |
| deepseek-v4-flash | Translate Gemma | fluency | 23 | 9.652 | 95.7% | -0.1303 (n=23) | +0.0993 (n=23) | -0.0735 (n=23) |
| deepseek-v4-flash | Translate Gemma | style | 20 | 8.600 | 65.0% | -0.0677 (n=20) | +0.1007 (n=20) | +0.3383 (n=20) |
| deepseek-v4-flash | Translate Gemma Refined | accuracy | 21 | 9.619 | 100.0% | -0.0162 (n=21) | +0.0810 (n=21) | +0.0486 (n=21) |
| deepseek-v4-flash | Translate Gemma Refined | fluency | 23 | 9.826 | 100.0% | -0.5361 (n=23) | -0.2940 (n=23) | +0.3632 (n=23) |
| deepseek-v4-flash | Translate Gemma Refined | style | 22 | 8.773 | 59.1% | +0.2358 (n=22) | +0.2949 (n=22) | -0.0609 (n=22) |
| gemini-3.1-flash-lite | Qwen3.6-27B | accuracy | 198 | 9.460 | 95.5% | -0.0003 (n=198) | -0.0036 (n=198) | +0.1298 (n=198) |
| gemini-3.1-flash-lite | Qwen3.6-27B | fluency | 198 | 9.606 | 97.0% | -0.2455 (n=198) | -0.1815 (n=198) | +0.1307 (n=198) |
| gemini-3.1-flash-lite | Qwen3.6-27B | style | 198 | 8.657 | 70.2% | -0.0140 (n=198) | +0.0409 (n=198) | +0.1359 (n=198) |
| gemini-3.1-flash-lite | Qwen3.6-27B Refined | accuracy | 198 | 9.500 | 97.5% | +0.0731 (n=198) | +0.0460 (n=198) | +0.1505 (n=198) |
| gemini-3.1-flash-lite | Qwen3.6-27B Refined | fluency | 198 | 9.535 | 95.5% | -0.2654 (n=198) | -0.1544 (n=198) | +0.2617 (n=198) |
| gemini-3.1-flash-lite | Qwen3.6-27B Refined | style | 198 | 8.621 | 67.7% | -0.0069 (n=198) | -0.0786 (n=198) | +0.0413 (n=198) |
| gemini-3.1-flash-lite | Translate Gemma | accuracy | 198 | 9.429 | 96.0% | -0.1957 (n=198) | -0.1253 (n=198) | +0.2015 (n=198) |
| gemini-3.1-flash-lite | Translate Gemma | fluency | 198 | 9.439 | 93.9% | -0.3322 (n=198) | -0.1851 (n=198) | +0.2845 (n=198) |
| gemini-3.1-flash-lite | Translate Gemma | style | 198 | 8.667 | 72.2% | -0.0839 (n=198) | -0.1434 (n=198) | +0.2374 (n=198) |
| gemini-3.1-flash-lite | Translate Gemma Refined | accuracy | 198 | 9.525 | 98.0% | -0.1673 (n=198) | -0.1552 (n=198) | +0.2476 (n=198) |
| gemini-3.1-flash-lite | Translate Gemma Refined | fluency | 198 | 9.515 | 96.0% | -0.3407 (n=198) | -0.1418 (n=198) | +0.3104 (n=198) |
| gemini-3.1-flash-lite | Translate Gemma Refined | style | 198 | 8.752 | 74.2% | -0.0372 (n=198) | -0.1385 (n=198) | +0.1826 (n=198) |
| gemini-3.1-flash-lite-think | Qwen3.6-27B | accuracy | 198 | 9.662 | 98.0% | -0.0226 (n=198) | +0.0291 (n=198) | +0.1053 (n=198) |
| gemini-3.1-flash-lite-think | Qwen3.6-27B | fluency | 198 | 9.919 | 99.5% | -0.1757 (n=198) | -0.2399 (n=198) | +0.0982 (n=198) |
| gemini-3.1-flash-lite-think | Qwen3.6-27B | style | 198 | 9.066 | 86.9% | -0.0409 (n=198) | +0.0150 (n=198) | +0.1852 (n=198) |
| gemini-3.1-flash-lite-think | Qwen3.6-27B Refined | accuracy | 198 | 9.758 | 99.5% | -0.0349 (n=198) | -0.0622 (n=198) | +0.0793 (n=198) |
| gemini-3.1-flash-lite-think | Qwen3.6-27B Refined | fluency | 198 | 9.909 | 98.5% | -0.1514 (n=198) | -0.0725 (n=198) | +0.0891 (n=198) |
| gemini-3.1-flash-lite-think | Qwen3.6-27B Refined | style | 198 | 9.071 | 86.9% | -0.0257 (n=198) | +0.0307 (n=198) | +0.0576 (n=198) |
| gemini-3.1-flash-lite-think | Translate Gemma | accuracy | 198 | 9.576 | 96.0% | -0.1933 (n=198) | -0.0833 (n=198) | +0.2308 (n=198) |
| gemini-3.1-flash-lite-think | Translate Gemma | fluency | 198 | 9.843 | 98.5% | -0.1865 (n=198) | -0.1003 (n=198) | +0.2202 (n=198) |
| gemini-3.1-flash-lite-think | Translate Gemma | style | 198 | 8.924 | 80.8% | -0.1893 (n=198) | -0.0959 (n=198) | +0.2274 (n=198) |
| gemini-3.1-flash-lite-think | Translate Gemma Refined | accuracy | 198 | 9.722 | 97.5% | -0.0553 (n=198) | +0.0398 (n=198) | +0.1844 (n=198) |
| gemini-3.1-flash-lite-think | Translate Gemma Refined | fluency | 198 | 9.818 | 96.5% | -0.1454 (n=198) | -0.0976 (n=198) | +0.1497 (n=198) |
| gemini-3.1-flash-lite-think | Translate Gemma Refined | style | 198 | 9.040 | 86.9% | -0.2018 (n=198) | -0.0397 (n=198) | +0.3205 (n=198) |
| gpt-5.5 | Qwen3.6-27B | accuracy | 198 | 9.192 | 85.9% | -0.0325 (n=198) | +0.0836 (n=198) | +0.1510 (n=198) |
| gpt-5.5 | Qwen3.6-27B | fluency | 198 | 9.591 | 94.4% | -0.1194 (n=198) | -0.0192 (n=198) | +0.0924 (n=198) |
| gpt-5.5 | Qwen3.6-27B | style | 198 | 8.288 | 32.8% | -0.1679 (n=198) | -0.0054 (n=198) | +0.3232 (n=198) |
| gpt-5.5 | Qwen3.6-27B Refined | accuracy | 198 | 9.278 | 89.4% | -0.0553 (n=198) | -0.0055 (n=198) | +0.1971 (n=198) |
| gpt-5.5 | Qwen3.6-27B Refined | fluency | 198 | 9.566 | 97.5% | -0.0890 (n=198) | +0.0881 (n=198) | +0.0922 (n=198) |
| gpt-5.5 | Qwen3.6-27B Refined | style | 198 | 8.308 | 34.3% | -0.2025 (n=198) | -0.0040 (n=198) | +0.3150 (n=198) |
| gpt-5.5 | Translate Gemma | accuracy | 198 | 9.177 | 85.4% | -0.2452 (n=198) | -0.0556 (n=198) | +0.2491 (n=198) |
| gpt-5.5 | Translate Gemma | fluency | 198 | 9.182 | 82.8% | -0.1569 (n=198) | +0.0293 (n=198) | +0.1836 (n=198) |
| gpt-5.5 | Translate Gemma | style | 198 | 8.379 | 40.9% | -0.1897 (n=198) | -0.0193 (n=198) | +0.2655 (n=198) |
| gpt-5.5 | Translate Gemma Refined | accuracy | 198 | 9.323 | 90.4% | -0.1805 (n=198) | -0.0438 (n=198) | +0.2056 (n=198) |
| gpt-5.5 | Translate Gemma Refined | fluency | 197 | 9.279 | 86.3% | -0.1348 (n=197) | -0.0213 (n=197) | +0.1637 (n=197) |
| gpt-5.5 | Translate Gemma Refined | style | 198 | 8.480 | 47.5% | -0.2291 (n=198) | -0.1005 (n=198) | +0.3093 (n=198) |
