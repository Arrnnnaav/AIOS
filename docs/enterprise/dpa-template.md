# Data processing addendum: template

> **A starting point, not legal advice.** Have counsel adapt it to your
> jurisdiction (UK/EU GDPR, CCPA, or other) before anyone signs it.

**Between** [Customer] ("Controller") and [Vendor] ("Processor"), for the
Orbyn desktop software.

1. **Subject matter.** Orbyn runs on the Controller's PCs. The Processor runs
   no service that receives Controller data. Data leaves a PC only to the model
   providers the Controller enables by policy (`AllowedProviders`,
   `CompanyEndpoint`), and only in the form described in
   `security-and-data-flow.md`.
2. **Categories of data.** Names and types of on-screen controls (scrubbed of
   emails, long numbers and key-like text), user goals typed into Orbyn, and
   Company Brain facts the Controller's owner approves. No screenshots unless
   the Controller sets `MaxEgress` to 2 and the user also turns pictures on.
3. **Processing location.** On the Controller's PCs and in the Controller's own
   shared folder. Model requests go where the chosen provider processes them;
   the Controller's agreement with that provider governs them.
4. **Sub-processors.** None appointed by the Processor. Model providers are
   chosen and contracted by the Controller.
5. **Security measures.** As listed in `security-and-data-flow.md`, including
   organisation policy, outbound redaction, signed team bundles, Credential
   Manager for keys, and a hash-chained local audit log.
6. **Retention and deletion.** Data stays on each PC until the user or
   Controller deletes `%LOCALAPPDATA%\GhostCursor`. The audit log is kept until
   deleted; the Controller sets its own retention.
7. **Data subject requests.** The Controller exports or deletes a person's
   data on their PC; the Processor holds none.
8. **Breach notice.** The Processor notifies the Controller without undue
   delay, and within [72] hours, of a vulnerability in Orbyn that exposed
   Controller data.
9. **Audit.** The Controller may review the source of the release it runs and
   the audit logs its PCs produce.

Signed: ______________________ (Controller)   ______________________ (Processor)
