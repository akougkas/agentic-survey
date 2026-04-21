# CITADL — A Knowledge Brief for Mira

*CITADL: Cyberinfrastructure for Intelligent, Trustworthy, Agentic Data Lifecycles.*

This document gives Mira the working conceptual ground she stands on during every CITADL interview. It is not a script, not a list of questions, and not a marketing summary. It is the distilled vision she is testing against the community's real experience. When a respondent uses unfamiliar vocabulary, Mira should search this brief for the nearest shared concept. When a respondent challenges the premise, Mira should be able to recognize which part of the vision they are pushing back on and probe for the specific disagreement. Treat this as the researcher's notebook before the field starts — thick enough to ground the conversation, thin enough to stay out of the participant's way.

## Why this work exists

Scientific productivity rhetoric and actual scientific workflow reality have drifted apart. On paper, we celebrate that experiments run faster, simulations scale wider, and storage gets cheaper every quarter. In practice, a working scientist still spends a substantial fraction of any given week copying files between systems, hand-writing provenance notes after the fact, chasing format conversions, staging data onto whatever tier has room, and reconstructing what they did three months ago so the paper figures can be regenerated. The bottleneck is not compute and it is not storage. The bottleneck is the coordination work between the two and the coordination work between the scientist and the infrastructure. Agentic AI has matured to a point where that coordination work is something an autonomous system can plausibly carry, at scale, for researchers who today carry it by hand. The community's question is not whether coordination can be automated in principle. The question is whether it can be automated in a way that scientists trust, operators will deploy, and institutions will sustain. That question is what the interviews are actually for.

## The scientific data lifecycle, phase by phase

The field has settled on six phases as a shared frame. Each phase has a purpose, a characteristic pain, and a set of tools that address it partially. The deeper story is not inside any single phase. It is in the handoffs between phases, which is where almost all the friction concentrates.

### Acquisition

Acquisition is where data enters the world. An instrument samples. A simulation writes to disk. A sensor network pushes events. The immediate question is always about configuration: what sampling rate, what precision, what metadata to attach at the moment of creation, what to discard before anyone has to think about it. Scientists today configure acquisition by hand or by per-experiment scripts because the instruments and the intent behind the campaign change faster than any rigid pipeline can accommodate. The pain at this phase is not that the data is missing. The pain is that the data enters the system stripped of the context that explains what it is, why it was generated, and what it was expected to show. That missing context has to be reconstructed downstream, often months later, under time pressure, with imperfect memory.

### Preparation

Preparation is the long tail of getting raw data into analysis-ready shape. Cleaning. Outlier handling. Unit normalization. Cross-instrument alignment. Metadata enrichment so the downstream tools can find what they need. Format conversion from whatever came off the instrument into whatever the analysis pipeline expects. In most domains, this is the single most time-expensive phase, and it is also the phase scientists most want to treat as uninteresting plumbing. The irony is that the choices made during preparation silently decide which scientific questions remain askable. A study design can survive bad storage. A study design rarely survives bad preparation, because the errors are invisible by the time they matter. Agentic preparation promises not only speed but consistency across campaigns, which is the precondition for cross-campaign meta-analysis.

### Storage

Storage is a policy problem disguised as a hardware problem. Once data exists, it has to live somewhere, and the choice of where — hot tier, warm tier, cold tier, archive, tape, cloud object store — depends on how often the data will be accessed, by whom, under what latency requirement, and for how long. Scientists today make these decisions by convenience rather than policy. The dataset lives where the person made it lives. It gets copied where someone needs it. Nothing migrates on its own. The result is that active data competes with stale data on the same hot tier, archival data that nobody has looked at in two years occupies capacity someone else needs this month, and the facility operator has no principled way to reclaim space without breaking someone's workflow. The agentic answer is not smarter tiering policies in isolation. It is tiering policies that understand what the scientist is actually doing and what they are about to do next.

### Movement

Movement is the phase that exists because the world is not a single machine. Data that was generated at an instrument facility has to move to a compute facility to be processed. Data that was processed on a cluster has to move to a cloud repository to be shared. Data that was archived at one institution has to move across a wide-area network to collaborators at another. Every one of these moves is today a scheduled, monitored, often manually-retried operation. Globus is the state of the art and it is still a person clicking through a browser or writing a Python script for each transfer. The agentic story in movement is that data should move because a downstream job is about to need it and the system knows the job is coming — not because a human realized three hours into the job run that the data is on the wrong side of the network.

### Decision support

Decision support is the phase most scientists don't name explicitly, which is why it is the phase most broken. It includes the moment a scientist asks "what have we done with this data before," or "what else correlates with this signal," or "where did this number come from, three derivations back." Today, each of these questions is answered by grep, by memory, by walking down the hall to ask a colleague, or by reading one's own lab notebook. Provenance systems exist but they live beside the data rather than with it. Discovery systems exist but each facility and repository has its own. The agentic vision for decision support is that when a scientist poses a question like these, the system has already pre-computed the discovery paths and can surface the answer in the conversational register of the question. The honest question is what fraction of researchers want that, versus being protective of the thinking-by-hand that the current friction preserves.

### Sharing

Sharing is the phase where the data meets the outside world. Publication to a journal. Upload to a community repository. Release under an embargo. Collaboration with a team at another institution. Compliance with a data management plan the funder required years earlier. Each of these has its own standards, its own metadata requirements, and its own gatekeepers. The scientist's experience of sharing is that it happens at the end of a project, under time pressure, with the archival details handled by whoever has the least leverage in the collaboration to refuse. The agentic answer is that sharing should be a continuous byproduct of the workflow rather than a terminal event. If preparation added the right metadata, if decision support tracked the right provenance, if storage policies anticipated the archival endpoint, then the act of sharing is nearly automatic. This is an aspiration the community has held for a long time. It has not been kept.

### The phase handoffs

The six phases are shorthand. The actual pain structure of scientific data work lives at the boundaries between them. Acquisition choices determine preparation effort. Preparation choices determine what storage layout makes sense. Storage layout determines movement feasibility. Movement determines what decision support can offer. Decision support determines what can be shared. Each handoff is today a manual reset where information about the prior phase is largely lost and has to be reconstructed. The central thesis of CITADL is that the handoffs themselves should be the locus of the agentic intervention. Not "a better preparation tool." Not "a better storage tool." A coordination layer that understands what happened in the previous phase well enough to shape the next phase usefully.

## Why agentic, and why now

The reason this vision is tractable now and was not tractable five years ago is that foundation models developed an emergent capacity for tool use, for long-horizon planning, and for natural-language intent interpretation at a fidelity that crosses a threshold. The older automation paradigm was to write a workflow manager, encode the steps as a directed graph, and let it execute. This worked when the steps were known in advance and the domain was narrow enough that the graph could be exhaustively specified. It does not work when the scientist's intent at the start of a project is vague, when the right sequence of steps emerges from early results, and when the domain spans enough heterogeneity that no single graph could be predefined.

Agentic AI changes the contract. The scientist says what they want. The system plans the first step, executes it, observes the result, and decides what to do next, within bounds the scientist has authorized. That loop is what scientists have always wanted from their tools and could never have from deterministic workflow managers. The loop also raises a new class of question that the field has not yet answered. When the agent's plan diverges from what the scientist would have done, whose plan wins? When the agent observes something surprising, does it ask or does it decide? When the agent makes an irreversible change, what are the guardrails? These are the questions the interviews need to probe, because the answer differs wildly by domain, by seniority, by institutional context, and by what the respondent has personally been burned by.

## The domain surface area

CITADL's claim to breadth rests on the argument that the same coordination pain recurs across domains whose surface details look nothing alike. The interview's job is to test this claim in specific cases rather than take it on faith.

### Materials discovery

A materials scientist runs hundreds of synthesis-characterization cycles a year, each generating terabytes of diffraction data, process telemetry, and DFT calculations that reference standard structure databases. The pain is that each cycle is treated as a standalone campaign. There is no persistent memory across cycles. The insight that would have made this cycle's parameter search converge faster was sitting in last quarter's data, unindexed.

### Biology, genomics, drug discovery

A genomics or drug-discovery workflow fuses heterogeneous datasets whose units, scales, and privacy constraints are incompatible. A single project might touch protein structures, clinical trial records, multi-omics panels, and a literature corpus whose entities resolve inconsistently across sources. The pain is that the cross-dataset joins are done by hand, and the provenance of those joins is usually undocumented, which means the work cannot be trusted at the reproducibility level regulators expect.

### Autonomous chemistry and self-driving laboratories

A self-driving lab runs closed-loop experiments where the previous experiment's result directly configures the next one, at a cadence faster than a human can supervise. The pain is that safety verification, data integrity checks, and the decision to stop the loop live in different places than the loop itself. When something goes wrong, the person who has to diagnose it is usually not the person who ran the campaign, and the traces they need to reconstruct what happened are scattered across the robot log, the analytics buffer, and the lab notebook.

### Neuroscience and brain-machine interfaces

A neuroscientist working with neural recordings has ultra-low-latency real-time requirements on one side and petabyte-scale archival requirements on the other. The pain is that the formats that preserve provenance well at archival scale are not the formats that support real-time streaming, and the conversion between them is lossy in ways that are discovered only at publication time.

### Earth sciences, climate, earthquake modeling

An earth sciences or earthquake-modeling group pulls from distributed sensor networks, long-running ensemble simulations, and international observation archives. The pain is that the data lives in administrative domains with incompatible access models, and the work of making it available to a single analysis runs through a combination of persuasion, bespoke scripts, and months of waiting for access reviews.

### Additive manufacturing and digital twins

An additive manufacturing team runs edge-instrumented printers that produce layer-wise data fast enough to trigger in-situ defect correction, while building a digital twin that needs the same data at archival fidelity on a different time scale. The pain is that the edge, cloud, and HPC sides of the operation each have their own storage and processing conventions, and the twin's fidelity is gated by whichever tier drops data first.

### Agriculture and environmental sensing

An agriculture or environmental-sensing project federates across field stations whose connectivity is intermittent, whose sensor populations are inconsistent, and whose data quality varies by grower. The pain is that the research questions are population-scale while the data collection is site-scale, and reconciling the two is where careers get made or stalled.

### Healthcare and clinical data

A healthcare research team operates under HIPAA and institutional review boards whose approval of data handling is explicit and time-bounded. The pain is that every new analysis requires a new review unless the original approval anticipated it, and the friction of re-review drives most teams toward over-specifying their original approval, which limits what they can then actually do.

### AI-driven research on AI itself

A growing population of researchers uses agentic AI systems as the research subject rather than the research tool. They run their own agents against scientific tasks and study what breaks. The pain they bring to CITADL is meta. They know where agents actually fail, which is exactly the evidence base CITADL needs to calibrate its own trustworthiness claims.

## The tools and infrastructure landscape

There is a production tool for nearly every phase of the lifecycle. HDF5 and its REST service for structured array storage. Object stores behind S3-compatible APIs for unstructured bulk. Parallel file systems for HPC hot paths. Globus and its API for wide-area transfer. Workflow managers for scheduling. Parquet and Zarr for columnar analytic access. Graph databases for provenance. Vector databases for retrieval over literature. Domain-specific standards such as NeXus for instruments, NWB for neural data, BIDS for neuroimaging, CIF for crystallography, FITS for astronomy. Each one is well-engineered within its scope. None of them coordinate with the others.

The honest assessment is that the tools are not the bottleneck. The coordination across tools is the bottleneck. CITADL does not intend to replace the tools. CITADL intends to place an agentic coordination layer above them that knows how to use each tool for what it is good at, negotiate format conversions when phases hand off, and surface the provenance of every decision back to the scientist in a form they can audit and override. Whether this is feasible at national scale is precisely what the planning year is meant to determine. The community's answer to that question — whether they believe it, whether they would bet their workflow on it, whether they would allow an agent inside their production operation — is the signal the interviews are extracting.

## Trust and irreducible human judgment

Every respondent has a line they will not let an agent cross. The line is not the same line for every respondent and the line is not located where introductory AI-safety writing would predict. For some, the line is at any action that modifies an instrument's configuration. For others, the line is at data deletion of anything they did not explicitly mark as deletable. For still others, the line is at any action that produces an artifact that will be attributed to them in a publication. The shape of that line — its location, its justification, and whether it is movable by evidence — is the single most valuable thing an interview can surface, because it is the operational definition of trust for the community CITADL will serve.

The interviews should treat trust not as a scalar the respondent rates on a five-point scale but as a map of zones. There are zones where the respondent will accept full autonomy. Zones where they want to be asked. Zones where they will review asynchronously. Zones where they insist on synchronous oversight. Zones where they refuse any agent involvement at all. The interview's job is to surface where those zones sit for this specific respondent and why. Generalizations across zones emerge at the cohort level, not at the individual level.

## Governance, sovereignty, sustainability

Autonomous agents operating on national-scale research data raise questions that the community has asked before about prior cyberinfrastructure efforts and never answered completely. Who owns the agents? Who owns the data the agents touch? When the agents trained on one institution's data improve their behavior in a way that benefits another institution, who captured the value? When the agents make a consequential error, who is responsible? When funding for the initial agent deployment expires, who keeps it running? None of these questions have clean answers today, and the absence of clean answers is a substantial part of why autonomous agents at scale in research infrastructure do not yet exist.

CITADL as a planning project cannot answer these questions for the community. It can surface the range of acceptable answers within the community, identify which models have precedent in other national infrastructure efforts, and propose a framework that each participating institution can adapt. The interviews are the input to that surfacing. The interviews should ask every respondent in an operator or institutional-leadership position what models they have seen work, what models they have seen fail, and what model they would propose if they had to build it tomorrow. Sustainability questions — how CITADL survives after the initial Category I award period, what funding models exist, what cost recovery looks like, what the transition path to a self-sustaining entity would be — belong in this same conversational territory and should not be siloed as a separate survey track.

## What a win actually looks like

A successful CITADL would reduce the scientist-visible friction of data lifecycle work by enough that the scientist could plausibly describe a research intent in natural language and expect the system to carry out the coordination that today they carry by hand. It would deploy on ACCESS and NDP resources as the reference substrate and federate to institutional infrastructure through a well-specified interface. It would maintain a trust posture where every agent action is auditable, every irreversible action is gated, and the line each scientist draws between autonomy and oversight is honored by the system rather than being the scientist's continuous manual work. It would be sustainable beyond the initial award and would evolve with the community rather than being frozen at the architecture of its initial deployment. These are the success conditions the community interviews are testing against the community's sense of what is achievable, what is desirable, and what is worth the investment.

## The open questions

There are questions CITADL has not answered and will not answer from the proposal text alone. The interviews exist because the questions exist. The most important of these are:

Whether the community actually wants natural-language intent as the primary specification mechanism or whether that is the proposal writer's preference imposed on a community that is comfortable with scripts. Whether the six-phase lifecycle frame captures how scientists actually think about their work or whether it is an operator's frame imposed on scientists whose own frame is experiment-centric and cuts across phases differently. Whether facility operators will in fact accept an external agentic coordination layer running inside their trust boundary. Whether AI researchers believe the current generation of foundation models is close enough to the required reliability for production deployment or whether we are a generation of models away. Whether the governance models the team has in mind are legitimate in the community's eyes. Whether the sustainability path is credible. And — R8 — whether the vision as stated is wrong somewhere in a way that the team has not seen because they live too close to it.

## Illustrative intents

Concrete sentences matter more than abstract descriptions. Some sentences the CITADL vision anticipates hearing, synthesized from prior exchanges with the community:

A materials scientist who wants to characterize phase evolution in a family of cathode compositions and compare with density-functional-theory predictions of vacancy ordering. A neuroscientist who wants to detect hippocampal replay events during sleep across subjects and correlate with behavioral data from the same cohort. A climate scientist who wants to assimilate multi-instrument remote-sensing observations into an ensemble forecast targeted at a specific Atlantic hurricane. A drug-discovery researcher who wants to traverse a knowledge graph of disease-gene-compound relations to surface candidate repurposings for a disease with few existing therapies. A self-driving chemistry lab operator who wants the next experiment's parameters chosen by a decision agent that has read the prior twenty experiments and the relevant safety constraints.

The interviews should invite every respondent to produce their own version of such a sentence. The cohort of sentences is arguably the single most valuable artifact the interviews produce.

## Glossary

Short definitions Mira can lean on when a respondent uses an unfamiliar term or challenges one of ours.

**Data lifecycle phase** — one of acquisition, preparation, storage, movement, decision support, sharing. The six-phase decomposition is a shared frame, not a universal truth. Respondents who cut it differently are worth probing about why.

**Agentic AI** — a system that takes autonomous actions toward a goal, using tools and feedback from its environment, within bounds set by a principal. Distinct from traditional automation because the action sequence is chosen at execution time rather than predefined.

**National Data Platform (NDP)** — an existing NSF-supported infrastructure intended as a substrate for data-intensive science services. CITADL's integration target.

**ACCESS** — the NSF program that provides compute and storage allocations to U.S. researchers. CITADL's other integration target.

**NAIRR** — the National AI Research Resource, a federal effort to provide AI infrastructure to the research community. CITADL coordinates with but does not replace.

**FAIR** — findable, accessible, interoperable, reusable. The principles the community agreed should govern scientific data. Rarely achieved in practice at the scale the proponents originally imagined.

**Provenance** — the record of where data came from, how it was transformed, and by whom. Structurally undertracked in today's workflows. One of the phases agentic systems could plausibly improve most.

**Trust zone** — an interview-derived concept for this study. The portion of a respondent's workflow where they will accept agent autonomy. Complements the zones where they want asynchronous review, synchronous oversight, or full manual control.

**Handoff** — the point at which data moves from one lifecycle phase to the next. The locus of most of the friction CITADL aims to reduce.

**Intent sentence** — a natural-language description of what a researcher wants a system to do, specific enough that an agentic system could plan execution. The artifact CITADL hopes to make the primary interface.
