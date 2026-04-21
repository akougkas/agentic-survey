**Community Survey**

**Three Survey Tracks**

Survey A: Domain Scientists

Survey B: Data Facility Operators & Tool Developers

Survey C: AI/ML Practitioners & Agentic AI Researchers

*NSF IDSS Planning Grant  |  Task 1 & Task 3 Deliverable*

**DRAFT — For Internal Review**  
**SURVEY A**

Domain Scientists & Research Engineers

This survey gathers information about how researchers across scientific and engineering domains manage data throughout their research workflows. Your responses will help us understand current practices, pain points, and opportunities for AI-assisted automation in the scientific data lifecycle. The survey has three tiers, progressing from background context through your current practices to forward-looking questions about autonomous data management.

**Tier 1: Background & Context**

*Establishing your research domain, data environment, and team composition.*

**Q1.** What is your primary research domain?

*\[Select all that apply\]*

☐  Materials science / chemistry

☐  Biology / genomics / drug discovery

☐  Neuroscience / brain-computer interfaces

☐  Earth sciences / climate / earthquake modeling

☐  Physics / astronomy / particle physics

☐  Agriculture / environmental science

☐  Additive manufacturing / engineering

☐  Healthcare / medical imaging

☐  Aerospace / hypersonics

☐  Social sciences / digital humanities

☐  Other (please specify): \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q2.** How would you characterize your role in the research data workflow?

*\[Select one\]*

☐  I primarily generate data (experiments, simulations, sensors)

☐  I primarily analyze and interpret data

☐  I do both generation and analysis

☐  I manage data infrastructure for my group

☐  I develop tools or methods used by others in my domain

**Q3.** How many people in your research group regularly interact with your data?

*\[Select one\]*

☐  1–2 (individual or small team)

☐  3–10 (lab group)

☐  11–50 (multi-group collaboration)

☐  51–200 (large project or consortium)

☐  200+ (community-scale)

**Q4.** What is the approximate total volume of data you or your group manage(s)?

*\[Select one\]*

☐  \< 1 TB

☐  1–10 TB

☐  10–100 TB

☐  100 TB – 1 PB

☐  \> 1 PB

**Q5.** What computing platforms do you use for your research? 

*\[Select all that apply\]*

☐  Local workstation / lab servers

☐  Institutional HPC cluster

☐  National HPC facilities (e.g., ACCESS, NERSC, OLCF)

☐  Commercial cloud (AWS, Azure, GCP)

☐  Edge devices / embedded sensors / instruments

☐  Self-driving or autonomous lab systems

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Tier 2: Current Data Lifecycle Practices**

*Understanding the specific phases of your data lifecycle, the tools you use, and where bottlenecks occur.*

*The scientific data lifecycle typically includes these phases: Acquisition (capturing data from instruments, simulations, or sensors), Preparation (cleaning, formatting, metadata tagging), Storage (placing data on appropriate storage tiers), Movement (transferring data between locations), Decision Support (analysis, visualization, provenance tracking), and Sharing (publishing, collaboration, archiving).*

**Q6.** Which phases of the data lifecycle consume the most of your (or your group’s) time and effort? Rank the top 3\.

*\[Rank top 3\]*

☐  Acquisition (instrument configuration, data capture)

☐  Preparation (cleaning, format conversion, metadata enrichment)

☐  Storage (managing where data lives, tiering, backup)

☐  Movement (transferring data between systems, staging for computation)

☐  Decision support (analysis, visualization, finding relevant prior data)

☐  Sharing (publishing datasets, compliance, creating repositories)

**Q7.** Describe a typical end-to-end data workflow in your research. Start from how data is generated and end with how results are published or shared.

*\[Open-ended (3–5 sentences)\]*

*Example: “We collect X-ray diffraction data at a synchrotron beamline, copy it to portable drives, transfer to our institutional cluster for preprocessing, run DFT calculations on a national facility, and manually package results for journal submission months later.”*

**Q8.** What data formats do you primarily work with?

*\[Select all that apply\]*

☐  HDF5 / NetCDF

☐  CSV / TSV / plaintext

☐  Domain-specific formats (FITS, NWB, BIDS, NeXus, CIF, etc.) — please specify: \_\_\_\_\_\_

☐  Images (TIFF, DICOM, microscopy formats)

☐  Relational databases (SQL)

☐  Graph databases / knowledge graphs

☐  Streaming or time-series data

☐  Parquet / Zarr / Arrow

☐  JSON / XML

☐  Proprietary instrument formats

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q9.** How do you currently manage metadata for your research data?

*\[Select all that apply\]*

☐  Manually maintained spreadsheets or notes

☐  Naming conventions on files and directories

☐  Domain-specific metadata standards (e.g., NeXus, NWB, Dublin Core)

☐  Automated extraction from instruments

☐  Lab information management system (LIMS)

☐  Electronic lab notebook

☐  We don’t systematically manage metadata

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q10.** What are the biggest pain points in your current data workflow? Rate each on a scale of 1 (not a problem) to 5 (critical bottleneck).

*\[Likert scale 1–5\]*

☐  Finding and locating previously generated data

☐  Tracking data provenance (who created what, when, and how)

☐  Reproducing previous analyses or results

☐  Moving large datasets between systems or facilities

☐  Converting between data formats

☐  Ensuring data quality and cleaning errors

☐  Getting data onto the right storage system at the right time

☐  Coordinating data across collaborators or institutions

☐  Complying with data sharing mandates (FAIR, journal requirements)

☐  Waiting for compute resources to process data

☐  Lack of real-time or near-real-time processing capability

**Q11.** When your data needs to move between systems (e.g., from an instrument to a cluster, from local to national facilities), how is that typically handled?

*\[Select all that apply\]*

☐  Manual copying (scp, rsync, USB drives)

☐  Globus or similar managed transfer service

☐  Custom scripts

☐  Cloud sync services (Dropbox, Google Drive, etc.)

☐  Automated pipeline (describe briefly): \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

☐  Data doesn’t typically move — we process in place

**Q12.** How do you currently decide where to store your data (e.g., local disk vs. cluster storage vs. tape archive vs. cloud)?

*\[Select one\]*

☐  I store everything in one place

☐  I manually move data between tiers based on how recently it was used

☐  My institution or facility has policies that dictate placement

☐  I have scripts or tools that automate some tiering decisions

☐  I don’t think about this — it’s someone else’s responsibility

**Tier 3: AI-Assisted and Autonomous Data Management**

*Exploring your readiness for, expectations of, and concerns about AI agents managing parts of your data lifecycle.*

*Agentic AI refers to AI systems that can act autonomously on your behalf, such as making decisions, executing tasks, and adapting workflows without step-by-step human direction. In data lifecycle management, such capabilities could mean AI agents that automatically clean your data, decide where to store it, move it to the right system before a computation begins, track provenance, or even suggest analyses based on your scientific intent.*

**Q13.** Have you used any AI or machine learning tools in your data management workflow (not for your scientific analysis, but for managing the data itself)?

*\[Select one\]*

☐  Yes, regularly

☐  Yes, occasionally or experimentally

☐  No, but I’m interested

☐  No, and I’m not sure it’s relevant to my work

☐  No, and I have concerns about it

**Q14.** If an AI agent could autonomously handle parts of your data lifecycle, which phases would you most want it to manage? Rank by priority.

*\[Rank top 3\]*

☐  Automatic data quality checks and cleaning upon acquisition

☐  Intelligent metadata extraction and tagging

☐  Automatic placement of data on the right storage tier

☐  Proactive data movement (prefetching data before a computation, staging results)

☐  Suggesting relevant datasets or prior results you should consider

☐  Automated compliance checking for sharing and publication

☐  Experiment design and hypothesis generation based on existing data

☐  Provenance tracking and reproducibility audit trails

**Q15.** Imagine you could describe your research intent in natural language (e.g., “Characterize phase evolution in these battery electrodes and compare it with prior compositions"), and an AI system would automatically orchestrate the data acquisition, preparation, analysis, and sharing. How valuable would such a system be?

*\[Select one\]*

☐  Transformative \- this would fundamentally change how I do research

☐  Very valuable \- would save significant time and effort

☐  Somewhat valuable \- useful for some tasks but not all

☐  Marginally valuable \- I’d still want to control most steps manually

☐  Not valuable \- I need full manual control over my workflow

**Q16.** What concerns do you have about autonomous AI agents managing your research data? Rate each on a scale of 1 (not concerned) to 5 (very concerned).

*\[Likert scale 1–5\]*

☐  AI making incorrect decisions that corrupt or lose data

☐  Lack of transparency in what the AI agent decided and why

☐  Security and unauthorized access to sensitive data

☐  Loss of scientific control or understanding of my own workflow

☐  Reproducibility — can I reproduce what the AI did?

☐  Bias in AI-driven data selection or analysis recommendations

☐  Compliance with domain-specific regulations (HIPAA, ITAR, etc.)

☐  Vendor lock-in or dependency on specific AI platforms

☐  Cost of AI-assisted infrastructure

**Q17.** For AI-assisted data management to be trustworthy in your domain, what would be essential? Select all that apply.

*\[Select all that apply\]*

☐  Full audit trail of every action the AI agent took

☐  Ability to approve or reject AI decisions before execution

☐  Ability to roll back any AI-initiated action

☐  Domain-specific validation of AI decisions (not generic checks)

☐  Explainability \- the agent must justify its decisions in terms I understand

☐  Human-in-the-loop for high-stakes decisions (e.g., deleting data, publishing)

☐  Compliance with my domain’s data governance standards

☐  Open-source and inspectable agent code

**Q18.** If a national-scale AI-assisted data management infrastructure were available, what would make you likely to adopt it? Select your top 3\.

*\[Select top 3\]*

☐  Integration with platforms I already use (ACCESS, institutional HPC, cloud)

☐  Natural language interface for specifying research intent

☐  Support for my domain’s data formats and standards

☐  Demonstrated success stories from researchers in my field

☐  No disruption to my existing workflows \- I can adopt gradually

☐  Training and documentation tailored to my domain

☐  Community governance (researchers have a voice in how it evolves)

☐  Free or low-cost access

**Q19.** Are there tasks in your data workflow that you believe should never be fully automated \- that always require human judgment? If so, which ones and why?

*\[Open-ended\]*

**Q20.** Is there anything else about your data management challenges or your vision for AI-assisted data workflows that you would like to share?

*\[Open-ended\]*

**SURVEY B**

Compute or Data Facility Operators & Tool/Library Developers

This survey is for operators of large-scale computing and data facilities, as well as developers of data management tools, libraries, and services. Your responses will help us understand the current landscape of production data infrastructure, the tools available for each phase of the data lifecycle, and the gaps that must be addressed to enable AI-assisted autonomous data management at a national scale.

**Tier 1: Background & Context**

*Establishing your role, facility, and the scope of data infrastructure you manage or develop.*

**Q1.** Which best describes your role?

*\[Select one\]*

☐  Facility operator / systems administrator at a computing or data center

☐  Storage systems architect or engineer

☐  Developer of data management tools or libraries (e.g., I/O libraries, storage systems, workflow tools)

☐  Research software engineer supporting scientific applications

☐  Platform or service lead for national cyberinfrastructure (e.g., ACCESS, NDP, NAIRR)

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q2.** What facility or organization do you work with?

*\[Select all that apply\]*

☐  University / institutional HPC center

☐  NSF-funded national facility (ACCESS resource provider, SDSC, TACC, etc.)

☐  DOE national laboratory

☐  Cloud service provider or commercial data center

☐  National or domain-specific data repository

☐  Software development organization (e.g., HDF Group, Globus)

☐  Instrument facility (synchrotron, telescope, sensor network)

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q3.** What is the approximate scale of data your facility or tool ecosystem supports?

*\[Select one\]*

☐  \< 100 TB

☐  100 TB – 1 PB

☐  1 PB – 10 PB

☐  10 PB – 100 PB

☐  \> 100 PB

**Q4.** How many distinct user communities or scientific domains does your facility/tool serve?

*\[Select one\]*

☐  1–2 specific domains

☐  3–5 domains

☐  6–10 domains

☐  10+ domains (general-purpose)

**Q5.** What storage tiers or technologies does your facility currently operate?

*\[Select all that apply\]*

☐  NVMe / local SSD

☐  Parallel file systems (Lustre, GPFS/Spectrum Scale, DAOS, WekaFS)

☐  Object storage (S3-compatible, Ceph, MinIO)

☐  Tape archive (HPSS, TSM)

☐  Cloud storage (AWS S3, Azure Blob, GCS)

☐  Network-attached storage (NFS, SMB)

☐  Database systems (relational, graph, time-series)

☐  Specialized streaming buffers or in-memory systems

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Tier 2: Data Lifecycle Tools, Libraries & Operational Practices**

*Understanding the tools you provide or develop, how they map to data lifecycle phases, and where operational gaps exist.*

*We define data lifecycle phases as: Acquisition (capturing/ingesting data), Preparation (cleaning, transformation, and metadata), Storage (placement, tiering, and management), Movement (transfer, staging, and replication), Decision Support (analysis interfaces, provenance, and discovery), and Sharing (publication, access control, and archival).*

**Q6.** For each data lifecycle phase, list the primary tools, libraries, or services your facility provides or your team develops. If you don’t address a phase, write N/A.

*\[Open-ended table\]*

*Phases: Acquisition | Preparation | Storage | Movement | Decision Support | Sharing. For each, describe: Tool/service name, current maturity (prototype / production / legacy), and number of active users.*

**Q7.** Which data lifecycle phases are currently the most operationally challenging for your facility? Rank the top 3\.

*\[Rank top 3\]*

☐  Acquisition — ingesting data at the rate it is produced

☐  Preparation — ensuring data quality, format standardization, metadata at scale

☐  Storage — tiering, capacity planning, cost management

☐  Movement — high-throughput transfer, cross-facility staging

☐  Decision Support — enabling users to discover, query, and track data

☐  Sharing — supporting FAIR principles, access control, compliance at scale

**Q8.** What are the biggest gaps in your current tool or service ecosystem? Rate each on a scale of 1 (not a gap) to 5 (critical gap).

*\[Likert scale 1–5\]*

☐  Automated metadata extraction at the point of data creation

☐  Intelligent or policy-driven data placement across storage tiers

☐  Real-time or streaming data ingestion pipelines

☐  Cross-facility data transfer orchestration (beyond point-to-point)

☐  Unified data discovery and search across heterogeneous repositories

☐  Provenance tracking that spans multiple tools and systems

☐  Automated data lifecycle policies (retention, migration, deletion)

☐  Self-tuning storage and I/O performance

☐  Format-agnostic data access layers

☐  User-friendly interfaces for non-expert researchers

**Q9.** How do you currently handle data placement and tiering decisions?

*\[Select all that apply\]*

☐  Manual user-driven (users decide where their data goes)

☐  Policy-based automation (rules based on age, size, access frequency)

☐  Quota systems (users get fixed allocations per tier)

☐  Hierarchical storage management (HSM) with automated migration

☐  We have a single tier — no tiering decisions needed

☐  Custom scripts or tools developed in-house

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q10.** What data format and interface standards does your facility or tool support?

*\[Select all that apply\]*

☐  HDF5 / HDF5-REST (HSDS)

☐  NetCDF / OPeNDAP

☐  Parquet / Arrow / Zarr

☐  POSIX file I/O

☐  S3-compatible object APIs

☐  Domain-specific formats (NeXus, NWB, BIDS, FITS, CIF)

☐  MPI-IO / parallel I/O libraries (PnetCDF, ADIOS)

☐  Globus Transfer API

☐  REST / GraphQL APIs for data access

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q11.** How do you monitor and optimize I/O and storage performance?

*\[Select all that apply\]*

☐  System-level monitoring tools (Darshan, TAU, Prometheus, Grafana)

☐  Application-level profiling (I/O tracing per job)

☐  User-reported issues (reactive troubleshooting)

☐  Automated anomaly detection

☐  Performance benchmarking (IOR, MDTest, etc.)

☐  We don’t systematically monitor storage performance

☐  Machine learning-based performance analysis

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q12.** What is the typical lifecycle of a dataset in your facility? Describe a common data flow from ingestion to eventual archival or deletion.

*\[Open-ended (3–5 sentences)\]*

**Tier 3: AI-Assisted Operations & Autonomous Data Management**

*Exploring how AI agents could integrate into facility operations and the challenges of deploying autonomous data management at scale.*

**Q13.** Has your facility or team experimented with AI/ML for any operational data management tasks (not scientific analysis)?

*\[Select one\]*

☐  Yes, in production

☐  Yes, in pilot/prototype stage

☐  We have explored it but not deployed

☐  No, but we are interested

☐  No, and we have significant concerns

**Q14.** If yes or exploring, which tasks have you applied AI/ML to?

*\[Select all that apply\]*

☐  Storage performance prediction or auto-tuning

☐  Anomaly detection in I/O patterns or system behavior

☐  Automated data placement or tiering decisions

☐  Metadata extraction or enrichment

☐  Predictive capacity planning

☐  Job scheduling optimization informed by data locality

☐  Data quality assessment

☐  Natural language interfaces for facility users

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q15.** For each data lifecycle phase, how feasible do you believe autonomous AI agent management is with current technology? Rate 1 (not feasible) to 5 (ready for production).

*\[Likert scale 1–5\]*

☐  Acquisition — AI agents configuring instruments and ingestion pipelines

☐  Preparation — AI agents performing automated data cleaning and enrichment

☐  Storage — AI agents making real-time tiering and placement decisions

☐  Movement — AI agents orchestrating cross-facility data transfers proactively

☐  Decision Support — AI agents tracking provenance and suggesting analyses

☐  Sharing — AI agents enforcing compliance and preparing publications

☐  Cross-phase coordination — AI agents optimizing across multiple lifecycle phases simultaneously

**Q16.** What are the biggest barriers to deploying AI agents in your production environment? Rate each 1 (minor) to 5 (showstopper).

*\[Likert scale 1–5\]*

☐  Security risks from autonomous actions on production systems

☐  Lack of training data from operational environments

☐  Unpredictable behavior of AI agents under novel conditions

☐  Integration complexity with existing tools and workflows

☐  Performance overhead of running AI inference alongside production workloads

☐  Accountability — who is responsible when an AI agent makes a mistake?

☐  Lack of explainability in agent decisions

☐  Regulatory and policy constraints on automated data handling

☐  Staffing — lack of expertise in both AI and facility operations

☐  Cost of AI compute resources for operational tasks

**Q17.** If a national-scale CITADL-like infrastructure were deployed, what integration model would work best for your facility?

*\[Select one\]*

☐  Agents run entirely within our facility, managed by our staff

☐  Agents run on external infrastructure (e.g., NDP) but interact with our systems via APIs

☐  Hybrid — some agents local, some external, coordinated through a federation layer

☐  We would need to evaluate based on specific security and policy requirements

☐  Our facility would not integrate with external autonomous agents

**Q18.** What interfaces or APIs would autonomous AI agents need to interact with your facility’s systems?

*\[Select all that apply\]*

☐  POSIX file system access

☐  S3-compatible object storage APIs

☐  Job scheduler APIs (Slurm, PBS, Flux)

☐  Data transfer APIs (Globus, SCP/SFTP)

☐  HDF5 REST API (HSDS)

☐  Authentication/authorization (OAuth 2.0, federated identity)

☐  Monitoring and telemetry APIs

☐  Metadata catalog APIs

☐  Custom facility-specific APIs — please describe: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q19.** What governance or trust requirements would need to be met before your facility would allow AI agents to perform autonomous actions on its systems?

*\[Open-ended\]*

*Consider: approval workflows, audit trails, rollback capabilities, sandboxing, certification of agent behavior, human-in-the-loop requirements.*

**Q20.** What capabilities would you most want from a next-generation national data management infrastructure? Select your top 3\.

*\[Select top 3\]*

☐  Unified data discovery across all NSF-funded facilities

☐  Automated cross-facility data staging and transfer

☐  Self-tuning storage and I/O performance

☐  Standardized provenance tracking across tools and platforms

☐  AI-assisted capacity planning and resource allocation

☐  Format-agnostic data access layer for heterogeneous storage

☐  Federated identity and access control across facilities

☐  Community-governed operational standards for AI agents

**Q21.** Is there anything else about your facility operations, tool development challenges, or vision for AI-assisted data infrastructure that you would like to share?

*\[Open-ended\]*

**SURVEY C**

AI/ML Practitioners & Agentic AI Researchers

This survey is for researchers and practitioners working on AI/ML systems, foundation models, multi-agent architectures, or AI-driven automation. Your responses will help us understand the current state of agentic AI capabilities, their readiness for scientific data management tasks, and the research challenges that must be addressed to enable trustworthy autonomous data lifecycle management at a national scale.

**Tier 1: Background & Expertise**

*Establishing your AI/ML specialization and experience with agentic or autonomous systems.*

**Q1.** What is your primary area of AI/ML expertise?

*\[Select all that apply\]*

☐  Foundation models (LLMs, vision-language models, multi-modal models)

☐  Multi-agent systems and coordination

☐  Reinforcement learning and decision-making

☐  AI for science (scientific ML, physics-informed ML, surrogate models)

☐  Knowledge graphs and reasoning

☐  Natural language processing and understanding

☐  Computer vision

☐  Robotics and cyber-physical systems

☐  AI safety, alignment, and trustworthiness

☐  MLOps / AI infrastructure / systems for ML

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q2.** How would you characterize your experience with agentic AI systems (AI that takes autonomous actions in an environment)?

*\[Select one\]*

☐  I actively research or develop agentic AI systems

☐  I have built or deployed agentic systems in production

☐  I have experimented with agent frameworks (e.g., LangChain, AutoGen, CrewAI, OpenAI Agents)

☐  I am familiar with the concepts but have not built agentic systems

☐  I am new to this area

**Q3.** In what application domains have you applied AI/ML?

*\[Select all that apply\]*

☐  Scientific research (physics, chemistry, biology, earth sciences, etc.)

☐  Healthcare / clinical / biomedical

☐  Manufacturing / engineering / robotics

☐  Software engineering / code generation

☐  Data management / databases / storage systems

☐  Cybersecurity

☐  Finance / business analytics

☐  General-purpose AI assistants / chatbots

☐  Autonomous laboratories / self-driving labs

☐  None yet — primarily methods research

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q4.** What scale of data have your AI/ML systems typically operated on?

*\[Select one\]*

☐  Small-scale (GBs, curated datasets)

☐  Medium-scale (TBs, institutional data)

☐  Large-scale (PBs, multi-facility or cloud-native)

☐  I work on methods; data scale varies

☐  Not applicable

**Tier 2: Agentic AI Capabilities for Data Lifecycle Phases**

*Understanding which data management tasks agentic AI can address today, which need research breakthroughs, and what architectural patterns apply.*

*The scientific data lifecycle has six phases: Acquisition (data capture from instruments/simulations), Preparation (cleaning, transformation, and metadata enrichment), Storage (placement across performance tiers), Movement (cross-system transfers), Decision Support (analysis, provenance, and discovery), and Sharing (publication, compliance, and archival). We are exploring how AI agents can autonomously manage these phases.*

**Q5.** For each data lifecycle phase, how would you assess the current maturity of agentic AI capabilities? Rate 1 (no viable approaches) to 5 (production-ready solutions exist).

*\[Likert scale 1–5\]*

☐  Acquisition — Agents that configure instruments, adaptive sampling, real-time filtering

☐  Preparation — Agents for automated data cleaning, format conversion, metadata extraction

☐  Storage — Agents for intelligent data placement, tiering, and retention decisions

☐  Movement — Agents for proactive data transfer, prefetching, in-flight processing

☐  Decision Support — Agents for hypothesis generation, provenance reasoning, experiment design

☐  Sharing — Agents for automated publication preparation, compliance checking, access control

☐  Cross-phase coordination — Multi-agent systems managing end-to-end data lifecycles

**Q6.** Which agentic AI architectural patterns do you believe are most applicable to scientific data management?

*\[Select all that apply\]*

☐  Single-agent with tool use (one LLM-based agent calling APIs and tools)

☐  Multi-agent collaboration (specialized agents for different tasks coordinating with each other)

☐  Hierarchical agents (supervisor agents delegating to sub-agents)

☐  Reactive agents (event-driven, responding to system state changes)

☐  Planning agents (goal-oriented, creating and executing multi-step plans)

☐  Learning agents (continuously improving from experience and feedback)

☐  Human-in-the-loop agents (acting autonomously but requesting approval for high-stakes decisions)

☐  Digital twin agents (maintaining a model of the system and simulating outcomes before acting)

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q7.** What foundation model capabilities are most critical for data lifecycle agents? Rank by importance.

*\[Rank top 5\]*

☐  Understanding domain-specific scientific context and terminology

☐  Reasoning about data schemas, formats, and relationships

☐  Planning multi-step workflows across heterogeneous systems

☐  Generating and executing code (Python, shell scripts, API calls)

☐  Natural language interaction with researchers for intent specification

☐  Processing and understanding multi-modal data (text, images, sensor signals, tables)

☐  Long-term memory and learning from past interactions

☐  Structured output generation (JSON, metadata schemas, configuration files)

☐  Uncertainty quantification and knowing when to ask for help

☐  Tool use and API integration with existing infrastructure

**Q8.** What are the most significant technical barriers to deploying agentic AI for data lifecycle management? Rate each from 1 (minor) to 5 (fundamental research challenge).

*\[Likert scale 1–5\]*

☐  Hallucination and factual errors in agent reasoning

☐  Lack of domain-specific training data for scientific data management

☐  Difficulty in specifying agent goals and constraints formally

☐  Agent coordination and conflict resolution in multi-agent settings

☐  Handling long-running tasks (hours to days) with state persistence

☐  Operating on heterogeneous data formats and storage systems

☐  Latency requirements (real-time decisions in milliseconds vs. minutes)

☐  Transfer learning across scientific domains

☐  Robustness to distribution shift (new instruments, new data types)

☐  Evaluation and benchmarking of agent performance in open-ended tasks

**Q9.** Describe an example of an agentic AI system you have built or studied that is relevant to data management, workflow automation, or scientific infrastructure. What worked well and what were the limitations?

*\[Open-ended\]*

**Q10.** For AI agents to coordinate across multiple data lifecycle phases (e.g., an acquisition agent triggering a preparation agent, which informs a storage agent), what coordination mechanisms are needed?

*\[Select all that apply\]*

☐  Shared state / blackboard architecture

☐  Message passing between agents (pub/sub, event bus)

☐  Centralized orchestrator / supervisor agent

☐  Shared ontology or knowledge graph for common understanding

☐  Formal contracts or service-level agreements between agents

☐  Reinforcement learning for emergent coordination

☐  Human-defined workflows with agent execution

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Tier 3: Trust, Safety, and Deployment at Scale**

*Addressing the challenges of trustworthy, safe, and governable autonomous AI in production scientific infrastructure.*

**Q11.** For autonomous AI agents operating on scientific data at national scale, which trust and safety mechanisms are most critical? Rank your top 5\.

*\[Rank top 5\]*

☐  Comprehensive audit logging of all agent actions and decisions

☐  Formal verification of agent behavior against safety specifications

☐  Sandboxed execution environments for untested agent actions

☐  Explainable decision-making (the agent can justify its actions)

☐  Graceful degradation (system continues safely if an agent fails)

☐  Rollback and undo capabilities for all agent-initiated changes

☐  Anomaly detection on agent behavior (detecting drift or errors)

☐  Human approval gates for irreversible or high-impact actions

☐  Red-teaming and adversarial testing of agent robustness

☐  Continuous monitoring and circuit breakers for autonomous operations

☐  Domain-expert validation of agent outputs before downstream use

**Q12.** What are the biggest risks of deploying autonomous AI agents in production scientific data infrastructure?

*\[Likert scale 1 (low risk) to 5 (critical risk)\]*

☐  Data loss or corruption from agent errors

☐  Cascading failures across interconnected agents

☐  Security vulnerabilities (prompt injection, unauthorized access via agents)

☐  Agents amplifying biases in data or analysis

☐  Loss of scientific reproducibility due to non-deterministic agent behavior

☐  Agents becoming a single point of failure for critical workflows

☐  Regulatory non-compliance from automated decisions

☐  Erosion of researcher skill and understanding of their own data

☐  Adversarial manipulation of agent behavior by bad actors

**Q13.** How should responsibility be assigned when an AI agent makes a consequential error in managing scientific data?

*\[Select one\]*

☐  The researcher who deployed or invoked the agent

☐  The developer of the agent or model

☐  The facility operator hosting the agent

☐  Shared responsibility with clear accountability frameworks

☐  This is an unsolved governance question that needs community input

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q14.** What approaches do you believe are most promising for ensuring AI agents can operate across diverse scientific domains without domain-specific retraining?

*\[Select all that apply\]*

☐  Fine-tuning foundation models on scientific data management corpora

☐  Retrieval-augmented generation (RAG) with domain-specific knowledge bases

☐  Modular agent architecture with swappable domain adapters

☐  Few-shot or in-context learning with domain examples

☐  Ontology-driven reasoning (using formal domain schemas)

☐  Collaborative filtering (learning from how agents performed in similar domains)

☐  Federated learning across facilities without sharing raw data

☐  Self-supervised learning from operational logs and system telemetry

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q15.** What evaluation frameworks or benchmarks would be needed to assess whether an AI agent is ready for production deployment in scientific data management?

*\[Open-ended\]*

*Consider: What metrics would you measure? What test scenarios are critical? How would you define success vs. failure?*

**Q16.** How should AI agents handle the tension between automation efficiency and scientific rigor? For example, an agent might produce results faster by skipping certain validation steps.

*\[Select one\]*

☐  Always prioritize rigor — agents must complete every validation, even at the cost of speed

☐  Allow configurable trade-offs that the researcher defines per task

☐  Agents should learn which validations are critical and which can be safely relaxed

☐  This depends entirely on the domain and risk level — needs per-domain policies

☐  Other: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_

**Q17.** For a national-scale AI-assisted data management infrastructure, what is the right balance between centralized and decentralized AI agent deployment?

*\[Open-ended\]*

*Consider: Should agents be trained/managed centrally or locally? Should there be a national agent registry? How should agent updates and versioning work across facilities?*

**Q18.** What open research problems must be solved to make agentic AI viable for end-to-end scientific data lifecycle management? List your top 3\.

*\[Open-ended\]*

**Q19.** Are there existing agentic AI frameworks, platforms, or tools that you believe could serve as a foundation for scientific data lifecycle agents? If so, which ones and what would need to be added or changed?

*\[Open-ended\]*

**Q20.** Is there anything else about AI capabilities, limitations, or your vision for autonomous data management that you would like to share?

*\[Open-ended\]*