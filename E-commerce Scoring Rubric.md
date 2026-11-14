# E-commerce Business Scoring Rubric (0–100)

You are scoring an e-commerce business with a fixed rubric. Follow these rules exactly. Do not use judgment, do not adjust scores for "context", and do not give in-between points. Every metric is scored by calculating one number and looking it up in a table.

---

## 0. Global rules (apply to every metric)

1. **Time window:** Use the trailing 12 months (TTM) unless a metric says otherwise.
2. **Use only the data provided.** Do not estimate, assume, or use industry averages to fill gaps.
3. **Missing data:** If the inputs for a metric are missing, that metric scores **0** and is listed as "MISSING". Do not guess.
4. **Not applicable (N/A):** A metric is N/A only where this rubric says so (e.g. inventory for dropshipping). N/A points are removed from the total possible, and the final score is rescaled (see Section 6).
5. **Rounding:** Round every calculated value to **2 decimal places** before looking it up in a table.
6. **Band boundaries:** Each table row includes its lower bound. "20.00–24.99%" means a value of 20.00 falls in that row and 25.00 falls in the next row up.
7. **One table lookup per metric.** Points come only from the tables. No partial or interpolated points.
8. **Currency:** Use the currency the data is in. Do not convert unless asked.

---

## 1. Standard definitions (use these formulas, nothing else)

| Term | Formula |
|---|---|
| **Revenue** | Gross sales minus discounts, before refunds. Excludes sales tax and shipping charged to the customer. |
| **COGS** | Landed product cost: unit cost + inbound freight to warehouse + duties/tariffs + packaging. **Does NOT include** platform fees, fulfillment fees, or advertising. |
| **Gross Profit** | Revenue − COGS |
| **Gross Margin %** | Gross Profit ÷ Revenue × 100 |
| **Net Profit** | Revenue − all expenses on the P&L (COGS, fees, ads, payroll including any owner salary, software, refunds, interest, depreciation, etc.), **before income taxes**. |
| **Net Margin %** | Net Profit ÷ Revenue × 100 |
| **SDE** | Net Profit + owner's salary and benefits (one owner only) + interest + depreciation & amortization + one-time expenses + personal expenses paid by the business. **Only include add-backs that are listed in the provided data.** |
| **SDE Margin %** | SDE ÷ Revenue × 100 |
| **AOV** | Revenue ÷ number of orders |
| **Conversion Rate %** | Orders ÷ sessions × 100. For Amazon use "Unit Session Percentage". |
| **Paid Revenue Share %** | Revenue attributed to paid ads ÷ total revenue × 100. |
| **Organic Revenue Share %** | 100 − Paid Revenue Share %. "Organic" = everything not paid: organic search, direct, email/SMS, referral, unpaid social, Amazon organic. |
| **Blended CAC** | Total advertising/marketing spend ÷ number of new customers (TTM). |
| **LTV** | AOV × Gross Margin % × average orders per customer. Average orders per customer = total orders ÷ unique customers over the last 24 months (use 12 months if only 12 are available, and note it). |
| **LTV:CAC** | LTV ÷ Blended CAC |
| **TACoS %** | Total ad spend ÷ total revenue × 100 |
| **Refund Rate %** | (Refunds paid + return processing/restocking costs) ÷ Revenue × 100 |
| **Platform & Fulfillment Fees %** | (Marketplace referral/commission fees + fulfillment fees (FBA or 3PL pick/pack) + storage fees + outbound shipping costs paid by seller + payment processing fees) ÷ Revenue × 100. Excludes advertising and software subscriptions. |
| **Inventory Turnover** | TTM COGS ÷ average inventory value at cost. Average inventory = (start-of-period inventory + end-of-period inventory) ÷ 2, or the average of monthly balances if provided. |
| **Repeat Customer Rate %** | Customers with 2+ orders in the TTM ÷ total unique customers in the TTM × 100 |
| **Revenue Volatility (CV) %** | Standard deviation of the last 12 monthly revenues ÷ average of those 12 months × 100 (use population standard deviation). |

---

## 2. A. Financial Health — 40 points

### A1. SDE / EBITDA — 15 points
Metric: **SDE Margin %**

| SDE Margin % | Points |
|---|---|
| 25.00 or higher | 15 |
| 20.00 – 24.99 | 12 |
| 15.00 – 19.99 | 9 |
| 10.00 – 14.99 | 6 |
| 5.00 – 9.99 | 3 |
| 0.00 – 4.99 | 1 |
| Below 0 | 0 |

### A2. Gross Profit Margin — 10 points
Metric: **Gross Margin %**

| Gross Margin % | Points |
|---|---|
| 60.00 or higher | 10 |
| 50.00 – 59.99 | 8 |
| 40.00 – 49.99 | 6 |
| 30.00 – 39.99 | 4 |
| 20.00 – 29.99 | 2 |
| Below 20.00 | 0 |

### A3. Net Profit Margin — 5 points
Metric: **Net Margin %**

| Net Margin % | Points |
|---|---|
| 20.00 or higher | 5 |
| 15.00 – 19.99 | 4 |
| 10.00 – 14.99 | 3 |
| 5.00 – 9.99 | 2 |
| 0.00 – 4.99 | 1 |
| Below 0 | 0 |

### A4. Revenue Consistency — 10 points (two parts, 5 + 5)

**A4a. Year-over-year growth (5 pts):** (TTM Revenue ÷ Prior 12-Month Revenue − 1) × 100. Needs 24 months of data, otherwise MISSING (0).

| YoY Growth % | Points |
|---|---|
| +20.00 or higher | 5 |
| +10.00 – +19.99 | 4 |
| 0.00 – +9.99 | 3 |
| −10.00 – −0.01 | 2 |
| −20.00 – −10.01 | 1 |
| Below −20.00 | 0 |

**A4b. Monthly stability (5 pts):** Revenue Volatility (CV) %. Needs 12 monthly revenue figures, otherwise MISSING (0).

| CV % | Points |
|---|---|
| 15.00 or lower | 5 |
| 15.01 – 25.00 | 4 |
| 25.01 – 35.00 | 3 |
| 35.01 – 50.00 | 2 |
| 50.01 – 75.00 | 1 |
| Above 75.00 | 0 |

A4 = A4a + A4b

---

## 3. B. Business Sustainability — 25 points

### B1. Organic vs. Paid Traffic — 10 points
Metric: **Organic Revenue Share %** (if revenue attribution is unavailable, use organic share of sessions instead and note it).

| Organic Share % | Points |
|---|---|
| 80.00 or higher | 10 |
| 70.00 – 79.99 | 8 |
| 60.00 – 69.99 | 6 |
| 50.00 – 59.99 | 4 |
| 40.00 – 49.99 | 2 |
| Below 40.00 | 0 |

### B2. Customer Acquisition Cost — 5 points
**Primary method:** LTV:CAC ratio (use when customer-level data exists, e.g. Shopify).

| LTV:CAC | Points |
|---|---|
| 4.00 or higher | 5 |
| 3.00 – 3.99 | 4 |
| 2.00 – 2.99 | 3 |
| 1.50 – 1.99 | 2 |
| 1.00 – 1.49 | 1 |
| Below 1.00 | 0 |

**Fallback method:** Use TACoS % only if customer counts are not available (common on Amazon). State which method was used.

| TACoS % | Points |
|---|---|
| 5.00 or lower | 5 |
| 5.01 – 8.00 | 4 |
| 8.01 – 12.00 | 3 |
| 12.01 – 15.00 | 2 |
| 15.01 – 20.00 | 1 |
| Above 20.00 | 0 |

### B3. Returns and Refunds — 5 points
Metric: **Refund Rate %**

| Refund Rate % | Points |
|---|---|
| 2.00 or lower | 5 |
| 2.01 – 4.00 | 4 |
| 4.01 – 6.00 | 3 |
| 6.01 – 10.00 | 2 |
| 10.01 – 15.00 | 1 |
| Above 15.00 | 0 |

### B4. Owner Dependency — 5 points
Score 1 point for each statement that is **clearly confirmed** by the provided data. If a statement is not mentioned or unclear, it scores 0.

| # | Statement | Points |
|---|---|---|
| 1 | Owner works 10 hours per week or less on the business. | 1 |
| 2 | Written SOPs exist for core operations (ordering, listings, customer service, fulfillment). | 1 |
| 3 | Daily operations are handled by employees, VAs, contractors, or agencies — not the owner. | 1 |
| 4 | The brand does not depend on the owner's personal identity (owner is not the face/influencer of the brand). | 1 |
| 5 | Supplier relationships are documented and transferable (contacts, contracts, or POs in the business's name). | 1 |

---

## 4. C. Operational Health — 20 points

### C1. Platform and Fulfillment Fees — 10 points
Metric: **Platform & Fulfillment Fees %**

| Fees % of Revenue | Points |
|---|---|
| 20.00 or lower | 10 |
| 20.01 – 25.00 | 8 |
| 25.01 – 30.00 | 6 |
| 30.01 – 35.00 | 4 |
| 35.01 – 40.00 | 2 |
| Above 40.00 | 0 |

### C2. Inventory Turnover / Stockouts — 10 points (two parts, 5 + 5)

**N/A rule:** If the business holds no physical inventory (dropshipping, print-on-demand, digital products), C2 is **N/A** — remove these 10 points from the total possible.

**C2a. Inventory Turnover (5 pts):**

| Turns per year | Points |
|---|---|
| 8.00 or higher | 5 |
| 6.00 – 7.99 | 4 |
| 4.00 – 5.99 | 3 |
| 3.00 – 3.99 | 2 |
| 2.00 – 2.99 | 1 |
| Below 2.00 | 0 |

**C2b. Stockout History (5 pts):** Count the number of stockout events in the TTM, where a stockout event = any one of the top 5 SKUs by revenue being out of stock for more than 3 consecutive days.

| Stockout events (TTM) | Points |
|---|---|
| 0 | 5 |
| 1 | 4 |
| 2 | 3 |
| 3 – 4 | 2 |
| 5 – 6 | 1 |
| 7 or more | 0 |

C2 = C2a + C2b

---

## 5. D. Growth Potential — 15 points

### D1. Average Order Value — 5 points
Metric: **AOV**

| AOV | Points |
|---|---|
| 100.00 or higher | 5 |
| 75.00 – 99.99 | 4 |
| 50.00 – 74.99 | 3 |
| 35.00 – 49.99 | 2 |
| 20.00 – 34.99 | 1 |
| Below 20.00 | 0 |

### D2. Conversion Rate — 5 points
Use the table for the business's **largest sales channel by revenue** only.

**Own website (Shopify, WooCommerce, etc.):**

| Conversion Rate % | Points |
|---|---|
| 4.00 or higher | 5 |
| 3.00 – 3.99 | 4 |
| 2.00 – 2.99 | 3 |
| 1.50 – 1.99 | 2 |
| 1.00 – 1.49 | 1 |
| Below 1.00 | 0 |

**Amazon / marketplace (Unit Session Percentage):**

| Unit Session % | Points |
|---|---|
| 20.00 or higher | 5 |
| 15.00 – 19.99 | 4 |
| 12.00 – 14.99 | 3 |
| 9.00 – 11.99 | 2 |
| 6.00 – 8.99 | 1 |
| Below 6.00 | 0 |

### D3. Customer Retention / LTV — 5 points
Metric: **Repeat Customer Rate %**

| Repeat Customer Rate % | Points |
|---|---|
| 35.00 or higher | 5 |
| 25.00 – 34.99 | 4 |
| 20.00 – 24.99 | 3 |
| 15.00 – 19.99 | 2 |
| 10.00 – 14.99 | 1 |
| Below 10.00 | 0 |

---

## 6. Final Score

1. **Points Earned** = sum of all metric points.
2. **Points Possible** = 100 minus the points of any N/A metrics (e.g. 90 if C2 is N/A). MISSING metrics are **not** removed — they stay in Points Possible and score 0.
3. **Final Score** = Points Earned ÷ Points Possible × 100, rounded to the nearest whole number.
4. **Data Completeness %** = (Points Possible − points of MISSING metrics) ÷ Points Possible × 100.

| Final Score | Rating |
|---|---|
| 85 – 100 | Excellent |
| 70 – 84 | Strong |
| 55 – 69 | Average |
| 40 – 54 | Weak |
| 0 – 39 | Poor |

If Data Completeness is below 70%, add the warning: "Score is unreliable — significant data missing."

---

## 7. Not scored (report only, for context)

These are useful to mention but **do not add or subtract points**:
- Cart Abandonment Rate
- Gross Profit in dollars
- Raw LTV and CAC dollar figures

---

## 8. Required output format

Respond in exactly this order:

**Step 1 — Calculation table.** One row per metric:

| Metric | Inputs used | Formula | Calculated value | Band | Points | Max |
|---|---|---|---|---|---|---|

Mark any metric as MISSING or N/A in the "Points" column.

**Step 2 — Section totals:** A (/40), B (/25), C (/20), D (/15).

**Step 3 — Final score:** Points Earned, Points Possible, Final Score, Rating, Data Completeness %.

**Step 4 — Notes:** Fallback methods used (e.g. TACoS instead of LTV:CAC, sessions instead of revenue for traffic), assumptions forced by the data, and cart abandonment if provided.

Do not change any score after Step 1. Commentary in Step 4 must not change points.
