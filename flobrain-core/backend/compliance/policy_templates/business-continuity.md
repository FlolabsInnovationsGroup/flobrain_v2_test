# Business continuity policy

**Organization:** {{ORG_NAME}}
**Owner:** {{POLICY_OWNER}}
**Effective:** {{EFFECTIVE_DATE}}
**Review:** every 12 months and after any real disruption

> Template. Adjust it to your setup before you publish it.

## 1. Purpose

Keep serving customers and protect information when something big goes wrong: a cloud outage, losing
key people, a security incident, or losing an office.

## 2. What matters most

| Service | Most downtime we accept | Most data we can lose |
|---|---|---|
| {{CRITICAL_SERVICE}} | {{RTO}} | {{RPO}} |
| Internal collaboration (FloBrain) | 1 working day | 24 hours |

## 3. Preparation

- Backups run on a schedule and a restore is tested at least once a year.
- An org export from FloBrain is taken at least monthly and kept in a separate, protected place.
- At least two people can act as admin, so one absence does not block the organization.
- Contact details for key people and vendors are kept outside our main systems.

## 4. During a disruption

1. The policy owner or the most senior person available takes charge.
2. Follow the incident response policy where security is involved.
3. Tell customers what is affected and when we expect it back. Our status updates come first.
4. Restore the most important services first, in the order of the table above.

## 5. After

Write what happened, how long recovery took compared with the targets, and what to change. Update this
policy and the plan.

## 6. Testing

Run a tabletop exercise once a year, and a restore test once a year.
