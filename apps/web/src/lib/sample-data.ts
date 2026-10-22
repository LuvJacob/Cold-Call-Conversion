import type { Brief, Prospect, ProspectInput } from "./model.ts";

const samples: Record<
  string,
  {
    summary: string;
    facts: Brief["facts"];
    notes: string;
    uncertainty?: string[];
  }
> = {
  northstar: {
    summary:
      "A regional logistics business bringing its distribution sites onto a more consistent technology foundation.",
    facts: [
      {
        label: "Company context",
        text: "Operates six regional distribution centers with a mix of on-premise and cloud systems.",
        sourceIds: ["company"],
      },
      {
        label: "A useful starting point",
        text: "The sample technology roadmap prioritizes standardizing backup and recovery across sites.",
        sourceIds: ["roadmap"],
      },
      {
        label: "Recent development",
        text: "Two additional facilities are included in the fictional expansion plan.",
        sourceIds: ["company"],
      },
    ],
    notes:
      "Met briefly at the regional technology meetup.\nRunning a mixed VMware environment. Mentioned that restoring backups across locations takes too long.\n\nAsk about their recovery targets before discussing a solution.",
  },
  meridian: {
    summary:
      "A growing professional-services firm reviewing how its distributed teams access internal systems.",
    facts: [
      {
        label: "Company context",
        text: "The fictional company supports consultants working across three offices.",
        sourceIds: ["company"],
      },
      {
        label: "Current priority",
        text: "The sample roadmap includes simplifying remote access and reducing support overhead.",
        sourceIds: ["roadmap"],
      },
    ],
    notes:
      "Referral from our partner team. Interested in simpler onboarding for new consultants.",
  },
  atlas: {
    summary:
      "An industrial manufacturer exploring better visibility across its operational technology estate.",
    facts: [
      {
        label: "Company context",
        text: "The sample company operates manufacturing and assembly facilities.",
        sourceIds: ["company"],
      },
    ],
    notes:
      "Confirm the scope of the IT team. Previous notes mention an upcoming infrastructure refresh.",
    uncertainty: [
      "The demo sources disagree on the number of facilities. Confirm directly.",
      "The current technology budget is unknown.",
    ],
  },
};

export function createDemoBrief(
  p: ProspectInput & { fixtureKey?: string | null },
  now = new Date().toISOString(),
): Brief {
  const sample = p.fixtureKey ? samples[p.fixtureKey] : undefined;
  return {
    mode: "demo",
    preparedAt: now,
    summary:
      sample?.summary ??
      "No live company research has been performed. Use the seller-provided details and notes to prepare for this conversation.",
    facts: sample?.facts ?? [],
    sources: sample
      ? [
          {
            id: "company",
            title: "Company overview",
            publisher: "Fictional demo document",
            excerpt: `${p.company} is a fictional company in this sample workspace. ${sample.facts
              .filter((f) => f.sourceIds.includes("company"))
              .map((f) => f.text)
              .join(" ")}`,
            url: null,
          },
          {
            id: "roadmap",
            title: "Technology planning notes",
            publisher: "Fictional demo document",
            excerpt:
              sample.facts
                .filter((f) => f.sourceIds.includes("roadmap"))
                .map((f) => f.text)
                .join(" ") ||
              "This demo document does not establish the current technology budget.",
            url: null,
          },
        ]
      : [],
    roleContext: `For a ${p.role}, priorities may include team effectiveness, operational reliability, and investment trade-offs. This is general role guidance, not a verified fact about ${p.name}.`,
    questions: [
      {
        text: "What is the most important improvement your team wants to make this quarter?",
        basis: "General discovery guidance",
      },
      {
        text: p.notes.toLowerCase().includes("backup")
          ? "How do you measure a successful recovery across your different locations?"
          : "Where does the current approach create the most work for your team?",
        basis: p.notes.toLowerCase().includes("backup")
          ? "Suggested from your notes about backups"
          : "General discovery guidance",
      },
      {
        text: "What would need to change for this to become a priority?",
        basis: "A hypothesis to explore, not a confirmed need",
      },
    ],
    uncertainty:
      sample?.uncertainty ??
      (sample
        ? []
        : [
            "Company and person details have not been independently researched.",
          ]),
  };
}

export function createSeedProspects(): Prospect[] {
  const entries = [
    [
      "p-maya",
      "Maya Chen",
      "Northstar Logistics",
      "VP of Information Technology",
      "northstar",
      "ready",
      "list-outreach",
    ],
    [
      "p-jordan",
      "Jordan Ellis",
      "Meridian Consulting",
      "Director of IT",
      "meridian",
      "ready",
      "list-outreach",
    ],
    [
      "p-alex",
      "Alex Morgan",
      "Atlas Manufacturing",
      "Head of Infrastructure",
      "atlas",
      "partial",
      "list-outreach",
    ],
    [
      "p-sam",
      "Sam Rivera",
      "Cedar Health Systems",
      "IT Operations Manager",
      "",
      "not-started",
      "list-outreach",
    ],
    [
      "p-priya",
      "Priya Shah",
      "Fieldwork Studio",
      "Chief Technology Officer",
      "",
      "failed",
      "list-outreach",
    ],
    [
      "p-eli",
      "Eli Brooks",
      "Harbor Financial",
      "Director of Technology",
      "",
      "not-started",
      "list-outreach",
    ],
    [
      "p-robin",
      "Robin Park",
      "Meridian Consulting",
      "Chief Operating Officer",
      "meridian",
      "ready",
      "list-accounts",
    ],
    [
      "p-taylor",
      "Taylor Reed",
      "Atlas Manufacturing",
      "IT Director",
      "atlas",
      "partial",
      "list-accounts",
    ],
  ];
  return entries.map(
    ([id, name, company, role, key, status, listId], index) => {
      const p: Prospect = {
        id,
        listId,
        name,
        company,
        role,
        phone: `+1 (202) 555-01${String(index + 10).padStart(2, "0")}`,
        notes: samples[key]?.notes ?? "",
        fixtureKey: key || null,
        revision: 0,
        researchStatus: status as Prospect["researchStatus"],
        callStatus: id === "p-eli" ? "called" : "ready",
        outcome: id === "p-eli" ? "no-answer" : null,
        brief: null,
        researchError:
          status === "failed"
            ? "Demo scenario: a research source timed out. Retry to see the recovery flow."
            : null,
      };
      if (status === "ready" || status === "partial")
        p.brief = createDemoBrief(p);
      return p;
    },
  );
}
