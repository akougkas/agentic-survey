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
    noSummaryYet: 'Mira is still collecting the brief.',
  },
  invite: {
    closedTitle: 'This invitation is closed.',
    usedMessage: 'This invitation has already been redeemed.',
    revokedMessage: 'This invitation is no longer active.',
    freshLinkMessage: 'Ask the campaign operator for a fresh link if you still need to join this study.',
    statusEyebrow: 'Status',
    statusTemplate: 'This invite is marked "{status}" in the runtime.',
    consentTitle: 'Choose how you want to be cited.',
    anonymousTitle: 'Anonymous',
    anonymousDescription:
      'Your responses contribute to the analysis without attaching your name.',
    namedTitle: 'Named',
    namedDescription:
      'Your name can appear alongside quoted responses in later research outputs.',
    nextEyebrow: 'What follows',
    nextSteps: [
      'Mira opens with one precise question grounded in the campaign objectives.',
      'Each answer is graded silently for coverage and follow-up signal.',
      'The session closes with a short summary once the interview has enough signal.',
    ],
    enterConversationLabel: 'Enter the conversation',
  },
  chat: {
    finishedFooter: 'Mira has closed this session. The transcript is now read-only.',
    activeFooter: 'Answer in your own words. Mira will keep the thread focused one question at a time.',
    anonymousParticipant: 'Anonymous participation.',
  },
} as const;

