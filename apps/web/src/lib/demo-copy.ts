export const demoCopy = {
  campaigns: {
    overviewEyebrow: 'Campaign overview',
    overviewTitle: 'See what is live, what is ready, and where Mira still needs guidance.',
    overviewDescription:
      'Start blank drafts, launch seed-backed studies, and monitor invite and session health from one workspace.',
    totalCampaignsLabel: 'Campaigns',
    reviewReadyLabel: 'Ready for review',
    liveCampaignsLabel: 'Live campaigns',
    activeSessionsLabel: 'Active sessions',
    blankPathEyebrow: 'Blank draft path',
    blankPathTitle: 'Start from a blank brief',
    blankPathDescription:
      'Open a designer thread and let Mira turn your constraints into a reviewable outline.',
    seedPathEyebrow: 'Seed-backed path',
    seedPathTitle: 'Start from a mounted seed',
    seedPathDescription:
      'Launch a declared campaign seed when the bundle already defines the outline and readiness criteria.',
    detailBackLabel: 'Back to campaigns',
    workflowEyebrow: 'Campaign state',
    workflowTitle: 'Move the study forward deliberately.',
    readinessEyebrow: 'Readiness',
    readinessTitle: 'Review gate',
    revisionsEyebrow: 'Outline revisions',
    revisionsTitle: 'What changed between drafts',
    outlineEyebrow: 'Current outline',
    outlineTitle: 'What Mira will actually run',
    invitesEyebrow: 'Invites',
    invitesTitle: 'Participant access',
    sessionsEyebrow: 'Sessions',
    sessionsTitle: 'Participant progress',
    designerTitle: 'Campaign Designer',
    designerFooter: 'Mira keeps the brief moving toward a reviewable outline.',
    seededReadyMessage:
      'This campaign came from a mounted seed and opened ready for operator review.',
    reviewBlockedMessage:
      'Finish the readiness checks before moving this campaign into review.',
    reviewingInviteHint:
      'Links can be prepared during review, but redemption stays blocked until the campaign is live.',
    liveInviteHint: 'New links can be redeemed immediately while the campaign is live.',
    emptySessions: 'No participant sessions have started yet.',
    emptyInvites: 'No invites have been created yet.',
    createInviteLabel: 'Generate invite',
    revokeInviteLabel: 'Revoke',
    openCampaignLabel: 'Open campaign',
    openTranscriptLabel: 'Open transcript',
    startFromSeedLabel: 'Start from seed',
    createDraftLabel: 'Create draft and open designer',
    noSummaryYet: 'Mira is still collecting the brief.'
  },
  invite: {
    header_eyebrow: 'Research Conversation',
    header_wordmark: '',
    header_subline: '',
    page_title: 'Research conversation invite',
    consent_title: 'Before we begin',
    anonymous_title: 'Contribute anonymously',
    anonymous_description:
      'Your responses contribute to the analysis without attaching your name.',
    named_title: 'Attribute your responses',
    named_description:
      'Your name or preferred citation can appear alongside quoted responses in the resulting research outputs.',
    micro_form_eyebrow: 'Orient Mira before you begin',
    micro_form_description:
      'A sentence or two so Mira opens in a register that fits your work.',
    micro_form_required_hint: 'This one is required before the conversation can begin.',
    micro_form_answer_note: 'Your answer stays between you, Mira, and the study team.',
    start_button_idle: 'Begin the conversation',
    start_button_pending: 'Starting the session...',
    next_eyebrow: 'How the conversation runs',
    next_steps: [
      'Mira opens with one precise question grounded in what you shared above.',
      'Each answer is graded silently for coverage and follow-up signal.',
      'You can skip, pause, come back later, or stop at any point.'
    ],
    closed_title: 'This invitation is no longer active.',
    closed_status_eyebrow: 'Status',
    closed_status_template: 'This invite is marked "{status}" in the study.',
    closed_used_message:
      'This invitation has already been redeemed. Each link is single-use.',
    closed_revoked_message: 'This invitation has been withdrawn by the study team.',
    closed_fresh_link_message: 'Contact the study team if you still need access.'
  },
  chat: {
    header_eyebrow: 'Research Conversation',
    header_wordmark: '',
    header_subline: '',
    page_title: 'Research conversation with Mira',
    conversation_heading: 'Conversation',
    transcript_locked_label: 'Transcript locked',
    agent_composing_label: 'Mira is thinking...',
    working_notes_eyebrow: "Mira's working notes",
    working_notes_heading: 'What I am tracking this session',
    retrieved_heading: 'Retrieved this turn',
    retrieved_description_singular:
      "Mira drew one passage from the study's grounding library.",
    retrieved_description_plural:
      "Mira drew {count} passages from the study's grounding library.",
    concepts_heading: 'Emerging concepts',
    concepts_empty: 'Mira will name concepts as they surface in your answers.',
    turn_counter_template:
      'Turn {count}. This is an open-ended conversation with no fixed length.',
    active_footer:
      'Answer in your own words. Mira keeps the thread focused one question at a time.',
    paused_footer:
      'Mira has paused this session. Resume when you are ready to continue.',
    finished_footer:
      'Mira has closed this session. The transcript is now read-only.',
    session_complete_eyebrow: 'Session complete',
    return_home_label: 'Return to home',
    empty_state:
      "The conversation will begin with Mira's first question as soon as the session is ready.",
    placeholder_default: 'Answer in your own words.',
    placeholder_with_chips: 'Tap one of the anchors above, or write your own answer.',
    submit_idle: 'Send',
    submit_pending: 'Working...',
    submit_finished: 'Session complete'
  }
} as const;
