# Single-node live Act diagnostic

**Status: diagnostic only, not acceptance evidence.** This one-node run does
not mint a production plan approval and cannot close an Act gate.

The retained record `diagnostic-node-failure.json` has SHA-256 `5157836905fb380275f650d16a9ad603ed1a1cfc6b883e643485aabd99436745`.
Despite the inherited filename, the record reports a verified
`powerpoint.new_slide_uia` node; it is not a failure transcript. Its lifecycle
and timing fields are retained as diagnostic observations only.

No second live run was performed for this citation repair. The artifact bytes
were left unchanged. The hygiene check parses structured JSON values
individually, so digits from unrelated fields are not concatenated into a
fictitious window handle; a complete observed value in any individual field
continues to be rejected.
