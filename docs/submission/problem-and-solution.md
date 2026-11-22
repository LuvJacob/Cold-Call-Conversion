# Problem and Solution Statement

## The problem: a productivity drain for reps and sales teams

B2B sales development reps (SDRs and BDRs) make dozens of cold calls a day to people they know almost nothing about. When a call connects, they have about ten seconds to show they understand the prospect's role, company and priorities. Researching every name takes far longer than reps have, so prep either eats hours of their day or doesn't happen.

That is a personal productivity problem for every rep and a team productivity problem for sales managers: time spent researching isn't spent talking to customers, prep quality varies from rep to rep, and research is repeated when two people call the same account. And a wrong fact loses trust in the first sentence.

## Our solution: Cold Call Conversion

An AI pre-call research assistant, built with IBM watsonx, that does the homework before the call and helps during it.

1. **Load a calling list.** Reps add prospects or import a CSV; lists are shared on the server.
2. **AI agents research in the background.** An orchestrator agent sends person and company research to sub-agents that gather approved public sources: SEC EDGAR filings, Wikidata, Wikipedia and the company's own website.
3. **IBM Granite on watsonx.ai turns sources into facts.** Granite reads each source and extracts structured facts (current role, company size, headquarters, recent news), each tied to the exact sentence it came from. Granite also writes the briefing summary and suggested opening questions.
4. **Verification keeps it honest.** Every Granite-extracted fact must quote its source verbatim, and our verifier cross-checks facts across sources, flags single-source facts as "unconfirmed", lists what is missing or stale, and drops anything it cannot confirm. If watsonx is unavailable, the system falls back to template wording, never invented facts.
5. **watsonx Orchestrate brings it into the seller's workflow.** The same research pipeline is packaged as a watsonx Orchestrate tool and agent, so a seller can ask "prepare me for a call with…" and get the cited briefing.
6. **Ready when the call connects.** The cited briefing is on screen, with a pop-out window over any dialer or CRM.
7. **Optional live transcript.** With consent, the app transcribes the call in the browser and shows cues when the prospect mentions pricing, a contract or a competitor, linking each to a relevant question from the briefing. No audio is saved.
8. **Log the outcome** and move straight to the next prepared lead.

## Productivity impact

- **Personal:** reps reclaim the minutes they spent researching each prospect, because research for a whole list runs in the background, and they start every call with a specific, sourced point.
- **Team:** every rep gets the same verified prep quality, briefings are cached and shared so accounts aren't researched twice, and managers can scale outreach without adding research hours.

We measure success by prep time saved, briefing usefulness and source coverage, with 21 automated evaluation scenarios checking every change.
