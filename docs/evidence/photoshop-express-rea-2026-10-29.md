# Adobe Photoshop Express (Adobe Express Photos): static teardown (29 October 2026)

Target: `AdobeSystemsIncorporated.AdobePhotoshopExpress` 6.9.30.0, the Store
package installed on the owner's machine the same day (498 MB). Nothing was
run; the package folder was listed and files were read as data (manifest,
feature-flag XML, model manifests, UTF-16 strings of two .NET assemblies).

## What it is

- WinUI/.NET 8 photo editor with WPF parts, a broker process
  (`PSExpressBroker`), a startup service and C2PA content credentials
  (`adobe_c2pa.dll`).
- Local ONNX/WinML models for select-subject, portrait segmentation,
  trimap and matting (`Resources/ModelsData`), shipped as encrypted `.data`.
- `ExpressPrtScBackgroundApp`: a tray app with a low-level keyboard hook that
  takes over Print Screen, Alt+Print Screen, Win+Print Screen and
  Win+Shift+S, captures the full screen or the active window, and opens the
  editor on the capture.
- `EditWithExpressVerb.dll`: an Explorer verb, "Open with Adobe Express
  Photos", that launches the broker with the file.
- A screen recorder (`ScreenRecording`), growth/monetisation feature flags,
  analytics (`AnalyticsBridge`, `dunamis-ingest`).

## What Orbyn took

- An Explorer verb, "Ask Orbyn about this file", that opens Ask a file with
  the file already loaded (`--ask-file`, `offer_file` / `take_offered_file`).
  Checked live on 29 Oct with a scratch topic: the page opened the sheet on
  its own showing the file name, and one question was answered from the file
  with "Sent 54 of 54 characters to the model".

## Not taken, and why

- Taking over Print Screen and sending captures: screenshots never leave the
  device (rule 6); a global key hook to steal a system shortcut is not
  something Orbyn does.
- The segmentation models: encrypted, Adobe's, and not a guide's job.
- Screen recording, analytics, monetisation flags: out of scope or egress.
