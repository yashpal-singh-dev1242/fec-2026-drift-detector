# Baseline failure at L tier

Attempted the direct-prompt baseline on 07_unit_change_currency at 50,000 rows.

Input: day1.csv 4,258,094 bytes + day2.csv 4,267,789 bytes (~2.1M tokens)
Model: claude-sonnet-5 (1M token context)

Result: rejected. `"result": "Prompt is too long"`, `"is_error": true`,
`"terminal_reason": "blocking_limit"`, exit code 1, 116 ms, $0.00.

The request never reached the model. This is not degraded performance --
the approach cannot run at this scale. Raw JSON: baseline_L_attempt.json
