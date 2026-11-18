<!--
Text for the Methodology page (app/pages/5_Methodology.py).
Each "## N." section is one step. The page shows the section, then a worked example
with the selected company's real numbers. Rewrite this in your own words: being able
to explain it is the point. Keep the "## N." headings so the page can find each step.
-->

## 1. Collect the numbers

Every number starts in an SEC filing. Company-wide figures (revenue, capex, operating income, depreciation) come from SEC's structured data for each 10-Q and 10-K. Revenue for the business line where AI should pay off, such as AWS or Google Cloud, isn't in that feed, so it's read from each filing's own XBRL data. Every value keeps the filing it came from.

Two details matter. Cash-flow figures in a 10-Q are year-to-date, so each quarter is the difference between two year-to-date totals. Q4 is never filed on its own, so it's the full year minus the first nine months.

## 2. Set the "before AI" baseline

ChatGPT launched on 30 November 2022. The baseline is the 15 quarters before it, from 2019 Q1 to 2022 Q3. Whatever the company did then is treated as its "normal" pace without AI. The window can be changed, and the Sensitivity page shows what happens when it is.

## 3. Estimate AI spending ("excess capex")

In the baseline, each company spent a fairly steady share of its revenue on capex. If it kept that ratio, today's capex would be that share of today's revenue. Anything above it is treated as AI spending.

**Formula:** baseline intensity = total capex ÷ total revenue in the baseline. Excess capex = actual capex − intensity × revenue. Cumulative excess capex adds this up from the first quarter after the baseline.

## 4. Estimate AI revenue ("excess revenue")

Fit a straight line through the tracked line's revenue in the baseline, so it grows by the same number of dollars each quarter, with a fixed seasonal pattern. Extend the line forward. That's the revenue the business would have had without AI. The gap above it is excess revenue. Multiply by the business's operating margin to turn it into profit.

A straight line means growth in percent slows as the business gets bigger, which is how large businesses usually behave. The alternative, constant percent growth, extends the 2019–22 pandemic cloud boom forever and leaves four of the five companies with no AI revenue at all. The app shows both and flags that the conclusion flips.

**Formula:** excess revenue = actual − trend. Excess profit = excess revenue × margin.

## 5. Return and payback

Two questions: how much of the extra spend has come back so far, and how long would today's extra profit take to cover it?

**Formula:** return so far = cumulative excess profit ÷ cumulative excess capex. Implied payback (years) = cumulative excess capex ÷ annualized excess profit, where annualized = the latest quarter × 4.

## 6. The depreciation wave

Capex doesn't hit profit when it's spent. It goes on the balance sheet and is expensed a little each quarter over the asset's useful life. Each quarter's capex is split into servers and network gear (60%, 6 years) and buildings (40%, 15 years), each expensed evenly from the next quarter. Future capex comes from management guidance.

Because a simple model can't see construction in progress, finance leases or changes in server life, it's scaled so the latest full year matches the depreciation the company actually reported.

**Formula:** quarterly depreciation of one quarter's capex = capex × share ÷ (life in quarters). Margin change = −(extra depreciation over the next 4 quarters ÷ today's revenue), with everything else held at today's level.

## 7. Scenarios

Nobody knows how fast AI revenue will keep growing, so there are three paths for the tracked line's revenue. Bull: today's growth continues, fading to half over 4 years. Base: growth fades to the pre-AI trend's pace over 3 years. Bear: revenue stays flat at today's level. Each path gives a payback date and a margin path.

## 8. Sensitivity

Change one assumption at a time and rerun every company. If a conclusion changes, the app says so: whether a company pays back at all, whether it shows any AI revenue, and which company pays back fastest or slowest.

## Known limits

- These are estimates, not true AI numbers. Some extra spending and growth would have happened anyway: normal cloud growth, non-AI data centers.
- Meta's AI payoff shows up inside ad revenue, so attribution is fuzzier. Microsoft's tracked line is Microsoft Cloud, which includes Microsoft 365 and Dynamics as well as Azure.
- Results depend on the baseline window and the shape of the trend. The Sensitivity page shows both.
- Capex here is cash spent on property and equipment. It leaves out equipment acquired through finance leases, which is large for Microsoft and was large for Amazon before 2022.
- The margin applied to excess revenue already includes today's depreciation, so subtracting extra depreciation in the scenarios double-counts a little.
- Capex guidance doesn't always measure the same thing as our capex. Each row's note says how, and Microsoft's is left out.
- AI revenue that lands in another company's books (for example, model labs paying cloud bills) counts only if it lands in a tracked line.
