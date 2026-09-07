# Email Holdout Test Analysis

**Test Period:** January 14, 2026 – 2026-03-06  
**Brands:** Burrow (BW), Havenly Pre-Converted (HAV PC), Interior Define (ID)  
**Data Sources:** Burrow & HAV — Braze Raw Events Datashare (Snowflake); ID — Braze Query Builder export  

---

## 1. Test Design

The holdout frequency test splits each brand's email list into two groups. The **control group** receives the full email cadence (all campaigns, same as before the test). The **holdout group** is excluded from certain sends, resulting in a lower send frequency. The cohorts are defined using two Braze campaign API IDs per brand: one campaign sent to the entire test universe (establishing cohort membership) and one sent exclusively to the control group (distinguishing control from holdout). No manual segment uploads are required — cohort membership is derived entirely from send events in the Braze raw events datashare.

The test launched **January 14, 2026** and remains live. Results are cumulative from the test start through today's date.

---

## 2. Send Frequency

Send frequency is measured as total emails sent per user within the test window.

| Brand | Control Sends/User | Holdout Sends/User | Reduction | Notes |
|-------|-------------------|-------------------|-----------|-------|
| HAV PC | 34.98 | 29.44 | -15.8% |  |
| Interior Define (ID) | 42.70 | 27.46 | -35.7% | *(email only)* |
| Burrow (BW) | 41.23 | 31.33 | -24.0% | *(email + SMS)* |

---

## 3. Performance Results

### 3a. Havenly Pre-Converted (HAV PC) — Conversion

| Metric | Control | Holdout | Delta |
|--------|---------|---------|-------|
| Users | 202,041 | 52,616 | — |
| Converters | 352 | 189 | — |
| Conversion Rate | 0.174% | 0.359% | +106.2% |
| Design Fee Events | 513 | 247 | — |

### 3b. Havenly Pre-Converted (HAV PC) — Email Engagement

| Metric | Control | Holdout | Delta |
|--------|---------|---------|-------|
| Users | 202,041 | 52,616 | — |
| Sends/User | 34.98 | 29.44 | -15.8% |
| Clicks/User | 0.1607 | 0.1796 | +11.8% |
| Unique Clicks/User | 0.1153 | 0.1357 | +17.7% |
| Clicker Rate | 5.170% | 5.890% | +13.9% |
| Opens/User | 20.3223 | 17.2228 | -15.3% |

### 3c. Havenly Pre-Converted (HAV PC) — AI Feature Engagement

| Metric | Control | Holdout | Delta |
|--------|---------|---------|-------|
| Explore AI Users | 166 | 48 | — |
| **Explore AI Rate** | **0.080%** | **0.090%** | **+12.5%** |
| Explore AI Events/User | 0.0011 | 0.0011 | — |
| AI Session Users | 489 | 132 | — |
| AI Session Rate | 0.240% | 0.250% | +4.2% |
| AI Session Events/User | 0.0041 | 0.0046 | — |

### 3d. Interior Define (ID) — Purchase & Revenue *(from QB export)*

| Metric | Control | Holdout | Delta |
|--------|---------|---------|-------|
| Users | 186,777 | 22,666 | — |
| Purchasers | 755 | 133 | — |
| Purchase Rate | 0.404% | 0.587% | +45.2% |
| Total Revenue | $2,488,361.31 | $369,570.88 | — |
| Revenue/User | $13.32 | $16.31 | +22.4% |
| Avg Order Value | $2,119.56 | $1,905.00 | -10.1% |
| Swatch Converters | 1,961 | 747 | — |
| Swatch Conv Rate | 1.050% | 3.296% | +213.9% |

### 3e. Burrow (BW)

| Metric | Control | Holdout | Delta |
|--------|---------|---------|-------|
| Users | 187,362 | 50,111 | — |
| Purchasers | 371 | 80 | — |
| Purchase Rate | 0.198% | 0.160% | -19.4% |
| Total Revenue | $517,930.00 | $104,565.00 | — |
| Revenue/User | $2.76 | $2.09 | -24.5% |
| Avg Order Value | $640.21 | $517.65 | -19.1% |
| Swatch Converters | 26 | 5 | — |
| Swatch Conv Rate | 0.014% | 0.010% | -28.1% |

---

## 4. Statistical Significance

Z-test for two proportions (two-tailed, α = 0.05).

| Brand | Metric | z-stat | p-value | Sig (95%)? | Direction |
|-------|--------|--------|---------|------------|-----------|
| BW | Purchase Rate | 1.75 | 0.07974 | NO | Control higher |
| BW | Swatch Conv Rate | 0.68 | 0.49739 | NO | Control higher |
| HAV PC | Design Fee Conv Rate | -8.21 | 0.00000 | **YES ✓** | Holdout higher |
| HAV PC | Clicker Rate | -6.57 | 0.00000 | **YES ✓** | Holdout higher |
| ID | Purchase Rate | -3.99 | 0.00006 | **YES ✓** | Holdout higher |
| ID | Swatch Conv Rate | -28.26 | 0.00000 | **YES ✓** | Holdout higher |

---

## 5. Incremental Impact Analysis

### Havenly Pre-Converted (HAV PC)

The holdout group converts at a significantly higher rate, suggesting the current email frequency is **suppressing conversions** for this segment.

- Control conversion rate: **0.174%**
- Holdout conversion rate: **0.359%**
- Excess holdout converters vs. expected at control rate: **97** users
- If the entire population converted at the holdout rate instead of the control rate, we would expect **+471** additional conversions across 254,657 total users.

### Interior Define (ID)

The holdout group generates more revenue per user, suggesting the current email frequency may be suppressing purchases.

- Control revenue/user: **$13.32**
- Holdout revenue/user: **$16.31**
- Holdout advantage per user: **$2.98**
- If the entire population converted at the holdout revenue rate, potential additional revenue across 209,443 users: **$624,652.19**

### Burrow (BW)

The control group generates more revenue per user than the holdout, suggesting email is incrementally driving purchases.

- Control revenue/user: **$2.76**
- Holdout revenue/user: **$2.09**
- Per-user differential: **$0.68** (control advantage)
- Holdout group size: 50,111 users
- Estimated incremental revenue from email (holdout at control rate − actual holdout): **$33,958.23**

> *Note: BW purchase rate difference is no longer statistically significant as of this report. The revenue differential has narrowed. Treat incremental estimate with caution.*

---

## 6. Changes from Previous Report (2/28 → 2026-03-06)

| Brand | Metric | 2/28 | 2026-03-06 | Trend |
|-------|--------|------|---------|-------|
| HAV PC | Conversion rate delta (hold vs ctrl) | +118.3% | +106.2% | Narrowing |
| HAV PC | Clicker rate delta | +15.3% | +13.9% | Narrowing |
| HAV PC | Ctrl sends/user | 31.71 | 34.98 | More sends |
| HAV PC | Holdout sends/user | 26.30 | 29.44 | More sends |
| HAV PC | p-value (conversion rate) | 0.0001 | 0.00000 | Still highly significant |
| ID | Purchase rate delta (hold vs ctrl) | +46.1% | +45.2% | Narrowing |
| ID | Swatch conv rate delta | +221.0% | +213.9% | Narrowing |
| ID | Revenue/user delta | +23.8% | +22.4% | Narrowing |
| ID | p-value (purchase rate) | 0.00006 | 0.00006 | Still highly significant |
| BW | Purchase rate delta (hold vs ctrl) | -24.2% | -19.4% | Narrowing |
| BW | Revenue/user delta | -25.1% | -24.5% | Narrowing |
| BW | p-value (purchase rate) | 0.032 | 0.07974 | Crossed above 0.05 ⚠ |

---

## 7. Key Takeaways

### Havenly Pre-Converted (HAV PC)

The holdout converts at 2.1× the control rate (0.359% vs 0.174%). This is statistically significant (highly significant).  The conversion gap has narrowed from +118.3% to +106.2%, but remains extreme. Email frequency appears to be actively suppressing conversions for this segment. Reducing send frequency for HAV PC is strongly supported by the data. Holdout users also show a +12.5% difference in `explore_with_ai` feature usage (0.090% vs 0.080%), suggesting email cadence may also affect AI feature engagement.

### Interior Define (ID)

The holdout generates +45.2% more in purchase rate and a +213.9% higher swatch conversion rate vs. control (3.296% vs 1.050%). Both are highly statistically significant (p=0.00006).  The purchase rate gap is stable (2/28: +46.1% → today: +45.2%). Email frequency is suppressing purchases and especially swatch conversions at ID.

### Burrow (BW)

The purchase rate gap narrowed from -24.2% to -19.4% and is **no longer statistically significant** (p=0.080 > 0.05, previously p=0.032). The control group's revenue/user advantage ($0.68) persists but is shrinking. Continue monitoring — the test may need a longer run to resolve.

---

*Report generated: 2026-03-06. Test window: January 14, 2026 – 2026-03-06.*
