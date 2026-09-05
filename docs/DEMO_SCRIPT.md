# ResumeRank v1.0 — two-minute demo and recording setup

**Presenter:** Olufemi Benua Keripe · **Project:** 3MTT Nextgen capstone
**Format:** screen recording with a small webcam overlay and your own narration.

The six beats below total **2:00**. Read only the quoted narration, not the stage directions.
There are about 230 spoken words: rehearse at a comfortable pace, leaving room for clicks.
The timings are a target, not a claim about API speed. Do not rush to match them if the app
is still loading; see the timing notes below.

The public project version is **v1.0**; the API's machine-readable version is `1.0.0`.

## 1. Prepare before pressing Record

- [ ] Use this updated checkout locally, or a deployment that contains these changes, so
      the on-screen wording and version match the guide. Editing the README does not update a live service.
- [ ] Open the [demo kit](../demo/README.md). Copy all of [the JD](../demo/job_description.txt)
      and have the four PDFs in `demo/resumes/` ready in a file picker. The vacancy and people
      are fictional; do not upload personal CVs for this recording.
- [ ] Open your deployed UI using the public URL shown in Render, or use the
      [local setup](../README.md#getting-started). Do not guess the Render hostname from its service name.
- [ ] Open [API readiness](https://resume-api-femi.fly.dev/health/ready) before recording
      (use `http://localhost:8000/health/ready` for a local API). It should return HTTP 200
      with `status: ready`. This is a **`SELECT 1` connectivity check**, not proof of correct
      migrations, enum bindings, or successful writes.
- [ ] Allow time for a cold UI or a recent deployment to settle. The checked-in Fly configuration
      keeps the API running and disables auto-start: a manually stopped machine is not guaranteed
      to wake just because you load its URL.
- [ ] Log in off-camera. Create an account first if necessary; use at least eight password
      characters, as required by the API. If a secret was rotated recently, log in again.
- [ ] Run one practice batch, then open **🗂 My History** and **📈 Analytics**. Confirm that
      the results were actually saved. Do not assume those pages start at zero or should
      increase by four on every rerun.
- [ ] Check **Source** in **🏆 Candidate Rankings**: `api` or `api (cached)` supports this
      demo. If it says `local`, the displayed fallback is not proof of a saved analysis.
      Check History, restore the API, and retry before recording the persistence section.
- [ ] Rehearse the scroll from **📑 Scores by Candidate** past **☁️ Skill & Keyword Cloud**
      to **🏆 Candidate Rankings** and **📤 Export Results**. Batch mode does not show the
      single-candidate score ring. Missing terms are in the API, not a UI panel.
- [ ] Return to **🔍 Screening**. If **🧹 Clear results** is visible, use it to clear the
      displayed result cards. It **does not delete database records or bypass the cache**.
      Remove the existing files from the upload widget and clear the JD text box separately
      so the input step does not append text or add the same files twice. Keep the file picker
      ready and the JD on the clipboard for the recorded input step.
- [ ] Close email, chat, Supabase/Fly/GitHub settings, password managers and unrelated tabs.
      Turn on Windows **Do not disturb**. Prefer a dedicated demo account/local instance
      so History/Analytics do not expose another person's information.

### A normal consequence of rehearsal: cached results

With default per-account deduplication, the recorded rerun may show `api (cached)` and
**Smart Cache Hits**. That is expected and does not add new History records. Do not call it
fresh processing or use its speed as a performance benchmark.

If you see cached results, replace the “backend also suggests…” sentence in beat 3 with:

> “This rerun reuses the saved analyses, which is why the source says API cached.”

Do not delete database rows just to make the take look new. If the API times out, first
check whether it finished server-side; local fallback does not automatically sync later.

## 2. The two-minute script

### 0:00–0:15 — introduction

**Screen:** Start logged in on **🔍 Screening**, with the webcam visible. Keep the
**🧪 Screening setup** card in view. Look at the camera for the first sentence.

> “Hi, I’m Olufemi Benua Keripe. This is ResumeRank, my 3MTT capstone. It compares resumes
> with a job description and gives a reviewer a starting point, rather than making a hiring decision.”

### 0:15–0:35 — inputs

**Screen:** Paste the supplied JD into **📄 Paste the Job Description**. Use
**📂 Upload Resume(s)** to select all four demo PDFs. Choose **Batch Screening** under
**Analysis mode:**. Do not type the JD or create an account during the take.

> “I’m using a fictional Senior Data Engineer vacancy and four synthetic resumes, not real
> applicants. I paste the job description, upload the four PDFs, and select Batch Screening
> so I can compare them together.”

### 0:35–0:55 — run the analysis

**Screen:** Click **⚡ Run AI Analysis** once. Let the progress panel finish. Scroll to
**🏆 Candidate Rankings** and point to **Source**. Use the cached-result substitution above
if appropriate; never narrate a successful save over an error or `local` result.

> “I’ll click Run AI Analysis. This screen uses a weighted keyword score. The backend also
> suggests a role and extracts some fields. The source column tells me whether each result
> came from the API or local fallback.”

### 0:55–1:20 — interpret the result, with limits

**Screen:** Point to Tunde's row and Ibrahim's row, then the **Matched keywords** column.
The UI uses filenames as candidate labels. Show **📤 Export Results** and click
**📥 Download CSV** if time permits; there is no need to open the spreadsheet on camera.
**📥 Download PDF** is the other export option.

> “Here, Tunde’s data-engineering resume has the strongest keyword overlap, while Ibrahim’s
> frontend resume has the weakest for this particular job. The matched keywords help explain
> the ranking. These percentages are not hiring probabilities, and missing words do not prove
> missing ability. I can export the results for review.”

**Do not memorise percentages.** The supplied-file check is in the [demo kit](../demo/README.md),
but use what your screen actually shows. This comparison is about a specific JD, not which
person is generally a better candidate.

### 1:20–1:45 — saved results and a summary

**Screen:** Click **🗂 My History**. Show **🗂 All analyses** and open
**🔍 Extracted fields (per candidate)** briefly. Then click **📈 Analytics** to show the
summary cards. Use **🔄 Refresh** if needed; do not claim a count has increased when the
run reused existing records.

> “In My History, I can revisit saved analyses and inspect extracted fields, such as names
> and contact details. Those still need checking against the originals. Analytics summarises
> the saved records; it does not tell us how accurate the system is, or whether a candidate
> should be hired.”

### 1:45–2:00 — stack and close

**Screen:** Stay on the clean Analytics view or return to the rankings. Look into the
camera for the closing line. No terminal, infrastructure tour, or unverified uptime claim is needed.

> “The application uses Streamlit, FastAPI and SQLAlchemy, with PostgreSQL in deployment.
> My next step is testing with more varied, permissioned resumes and improving access
> controls. This is ResumeRank, version one point zero.”

### Optional substitutions — not extra minutes

- **Need to show Admin?** Only on an account you already administer, and only with safe demo
  data: use **🛠 Admin** **instead of Analytics** in beat 5. Replace the Analytics sentence with:
  “I’m signed in as an admin, so this page also lets me view user activity and manage admin access.”
  Show **Admin Dashboard**; do not change anyone's access during the recording. If Admin is
  not visible, keep the main script rather than claiming you demonstrated it.
- **Running the lightweight SQLite setup?** The closing stack line already distinguishes
  deployment from the demo. If asked, say: “This local demo uses SQLite; deployment uses
  PostgreSQL. The minimal install uses keyword role profiles and regex extraction.”
- **Asked where Celery or semantic scoring is?** “They are separate optional worker code.
  The UI endpoint I demonstrated processes requests synchronously and uses keyword scoring.”
- **Asked about accuracy?** “I have development tests on generated and curated examples,
  not an independent evaluation of real applicants or hiring outcomes.”

## 3. Screen + face setup on Windows — OBS Studio

[OBS Studio](https://obsproject.com/) is a free option for recording the screen, webcam and
microphone together. No generated voice or background music is needed.

1. **Create a scene** called `ResumeRank demo`.
2. In **Sources**, click **+ → Window Capture** and select the browser showing the app.
   This avoids capturing the whole desktop, but browser tabs, dialogs and notifications
   can still reveal private information. If Window Capture is black or unreliable, try
   **Display Capture** after cleaning that desktop. Test before using either for the take.
3. Add **+ → Video Capture Device**, select your webcam, and keep it **above** the browser
   source in the list. Make it about **one-fifth of the frame width** (roughly 350–400 px
   on a 1920 px canvas). Put it in a spare corner; confirm it does not cover the run button,
   rankings, **Source**, or downloads on any page. Lock both sources once positioned.
4. In **Settings → Video**, use **1920 × 1080** for Base (Canvas) and Output (Scaled)
   Resolution, and **30 FPS**. Use **1280 × 720 / 30 FPS** if the machine struggles.
   Keep browser text legible; start around 100–110% browser zoom and check the recording.
5. Select the headset or external mic in **Settings → Audio → Mic/Auxiliary Audio**
   (or add one **Audio Input Capture** source, but do not capture the same mic twice).
   Mute **Desktop Audio** unless needed. Use headphones to prevent speaker feedback.
6. Watch the audio meter while speaking normally. Aim for peaks roughly **−12 to −6 dB**;
   avoid red/clipping. Make a **15-second test recording and play it back** to check speech,
   screen readability, webcam position and audio/video sync. A moving meter alone is not enough.
7. In **Settings → Output**, use **Simple** output mode and a recording quality such as
   **High Quality, Medium File Size**. Set the recording path **outside this repository**.
   Choose **Matroska (.mkv)** for the recording, which is safer if recording is interrupted.
8. Click **Start Recording**, leave a short quiet lead-in, perform the six beats, then click
   **Stop Recording**. Assign start/stop hotkeys under **Settings → Hotkeys** if convenient.
9. Use **File → Remux Recordings** to convert the MKV to **MP4** without re-encoding for
   sharing. Trim the setup/closing silence in a video editor if necessary. Suggested final
   filename: `ResumeRank_v1.0_demo.mp4`.

**Camera and room:** put the camera at eye level, frame head and shoulders, and face a window
or lamp. Avoid a bright window behind you. A quiet room and a clearly audible mic matter
more than an elaborate overlay. Keep the script near the camera, not on the captured screen.

### Easier alternative: Loom

If available on your account, [Loom](https://www.loom.com/) can capture the screen with a
camera bubble and mic, then provide a share link. Select the app window, test the audio,
and check the account's **current recording limits and sharing permissions** before relying
on it. Do not assume a particular free-plan duration or upload limit.

## 4. Timing, honesty and final checks

- Rehearse once with a timer. Aim for the spoken portion to finish slightly before 2:00,
  leaving the remaining time for pointer movement and page changes.
- If loading makes the take too long, cut only dead waiting time and label the cut, e.g.
  **“Processing wait shortened.”** Do not make an edited or cached run look like a speed test.
  If submission rules require one continuous take, pre-open the pages, rehearse, and retake instead.
- Keep the explanation of limitations even if you drop an optional download or Admin view.
  Do not add claims about eliminating bias, replacing recruiters, measured time savings,
  “production-ready” security, or general “100% accuracy.”
- Watch the **finished export**, not just the OBS preview: voice clear, no clipping/echo,
  face visible, text readable, real on-screen results matching narration, no secret values
  or personal documents, and a final duration of **2:00 or less** if that is the submission limit.
- Upload with appropriate sharing permissions and test the link while signed out. Only then
  replace **“Recording link: not added yet”** in the [README](../README.md#demo-video) with
  the real video link. Do not commit the video file to Git.
