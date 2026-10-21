# Access control policy

**Organization:** {{ORG_NAME}}
**Owner:** {{POLICY_OWNER}}
**Effective:** {{EFFECTIVE_DATE}}
**Review:** every 12 months

> Template. Adjust it to your setup before you publish it.

## 1. Accounts and sign-in

- Every person has their own account. Shared accounts are not allowed.
- Where the organization has single sign-on, it is enforced for company email domains. The owner
  keeps one break-glass sign-in, stored safely and used only in an emergency.
- Multi-factor authentication is required at the identity provider for everyone, and always for owners and admins.
- Where SCIM is available, people are added and removed automatically from the identity provider.

## 2. Granting access

- Access follows the role: owner, admin, team lead, member. Extra permissions are requested in FloBrain
  with a reason, decided by an admin, and given an end date where possible.
- Requests are decided within {{REQUEST_DAYS}} days.
- Owner and admin rights are kept to a small number of people (at most one in five members, never fewer
  than two who can act in an emergency).

## 3. Reviewing access

- Access is reviewed every quarter. Team leads review their team; admins review admins and anyone not in a team.
- Each item is kept, revoked or changed. Revocations are applied at once and recorded in the audit log.
- People who have not signed in for 90 days are reviewed and paused if they no longer need access.

## 4. Changing roles and leaving

- When someone changes role, access they no longer need is removed within 5 working days.
- When someone leaves, their account is paused or removed on their last day, their extra permissions are
  revoked and their personal connections to other services are disconnected.

## 5. AI and outside agents

- AI buddies only see what the person using them may see.
- Outside AI agents are connected only from hosts on the owner's allowlist, and only with a tool list the owner approved.
- Every action an AI proposes that writes or sends something waits for the person's approval.

## 6. Logging

Sign-ins, access changes and admin actions are recorded in the audit log and kept for at least 12 months.
