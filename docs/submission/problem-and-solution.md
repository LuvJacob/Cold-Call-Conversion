# Problem and Solution Statement

## The problem

B2B sales development reps (SDRs and BDRs) make dozens of cold calls a day to people they know almost nothing about. When a call connects, they have about ten seconds to show they understand the prospect's role, company and priorities. Doing that homework properly means searching LinkedIn, company sites, filings and news for every name on a list, which takes far longer than reps have. So prep either eats hours of the day or doesn't happen at all, and calls open generic and end fast.

The research that does happen is often unreliable: outdated, mixed up between people with the same name, or never checked. A rep who repeats a wrong fact loses trust in the first sentence. And during the call, useful context is buried in browser tabs when the prospect brings up budget, a renewal or a competitor.

## Our solution

Cold Call Conversion is an AI pre-call research assistant that does the homework before the call and helps during it.

1. **Load a calling list.** Reps add prospects or import a CSV; everything is saved on the server.
2. **AI agents research each prospect in the background.** An orchestrator agent sends person and company research to sub-agents. They pull from approved public sources (SEC EDGAR filings, Wikidata, Wikipedia and the company's own website), with paid search and enrichment providers ready to plug in.
3. **Every fact is verified and cited.** A verifier cross-checks findings, ties every fact to its source, flags single-source facts as "unconfirmed", lists what is missing or out of date, and drops anything it cannot confirm. Guardrails reject wrong-person matches, past roles, hedged claims and prompt-injection text. A thinner briefing beats an invented fact.
4. **The briefing is on screen when the call connects.** A prospect carousel shows a summary, cited facts, suggested opening questions and the uncertainty list. A pop-out window keeps the briefing on top of any dialer or CRM.
5. **Optional live call transcript.** With the seller's consent, the app transcribes the call in the browser and shows cue chips when the prospect mentions pricing, a contract, a competitor or a timeline, linking each to a related question or fact from the briefing. No audio is saved, and nothing is sent to our backend.
6. **Log the outcome and move on.** Reps record the call result and go straight to the next prepared lead.

## Impact

- **Less prep time:** research runs in the background in seconds per prospect instead of minutes of manual searching.
- **Better conversations:** reps open with a relevant, specific point and have the right question ready when the prospect raises a topic.
- **Trust:** every fact links to its source, and the assistant says when it isn't sure instead of guessing.
- **Responsible by design:** only approved public sources, no private personal data, consent before transcription and no stored audio.

We measure success by prep time saved, briefing usefulness and source coverage, and 21 offline evaluation scenarios check every change automatically.
