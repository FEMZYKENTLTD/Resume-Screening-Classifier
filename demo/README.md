# ResumeRank v1.0 — demo kit

Four **synthetic people** and a fictional Senior Data Engineer vacancy for trying the
application or recording the [two-minute walkthrough](../docs/DEMO_SCRIPT.md).
The company-style wording in the JD is illustrative, not a real vacancy or endorsement.

## Use it

1. Log in and select **🔍 Screening**.
2. Paste all of [`job_description.txt`](job_description.txt) into **📄 Paste the Job Description**.
3. Add all four PDFs from [`resumes/`](resumes/) to **📂 Upload Resume(s)**.
4. Select **Batch Screening** → **⚡ Run AI Analysis**.
5. Scroll to **🏆 Candidate Rankings**. Check **Source**, then confirm the saved records
   in **🗂 My History** before recording a persistence claim.

## Expected example, not an accuracy benchmark

Recomputed on **2026-09-05** with the committed PDFs, the exact bundled JD, and the default
[`scoring.score_details`](../scoring.py) keyword algorithm:

| PDF | Example keyword score | Role suggested by the bundled model with scikit-learn installed |
|---|---:|---|
| `tunde_bakare_data_engineer.pdf` | 57 | Data Engineering |
| `fatima_bello_data_scientist.pdf` | 21 | Data Science / ML |
| `chiamaka_eze_data_analyst.pdf` | 18 | Data Analytics / BI |
| `ibrahim_musa_frontend.pdf` | 0 | Frontend Engineering |

The scores describe vocabulary overlap with **this JD**, not candidate quality or hiring
probabilities. Tunde has the most matching terms; Ibrahim's frontend resume has no counted
matches for this vacancy. An unmentioned skill is not proof of a missing ability. For example,
the scorer can count both BigQuery and Snowflake even though the JD presents them as alternatives.

Do not memorise these percentages for narration. Edited inputs, an older saved result, a
different deployed scorer, or an explicitly invoked semantic worker can give different
numbers. Without the optional classifier dependency, the app uses keyword role profiles;
that does not change the synchronous endpoint's keyword score.

## Rehearsal and caching

- `api`: a result returned by the API. Check History while signed in to demonstrate persistence.
- `api (cached)`: the same account already analysed the same file bytes and JD. The saved
  result is reused; another four button submissions do not imply another four records.
- `local`: the UI produced a fallback result; this is not confirmation of a database write.
  Check whether any timed-out request completed, restore service and rerun as needed.

**🧹 Clear results** only clears the displayed results, not database rows or the cache.
A practice batch is useful for warming the app and checking History/Analytics, but describe
cached results honestly in the recording. Do not delete data to manufacture a fresh-looking run.
