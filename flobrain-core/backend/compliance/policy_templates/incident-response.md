# Incident response policy

**Organization:** {{ORG_NAME}}
**Owner:** {{POLICY_OWNER}}
**Effective:** {{EFFECTIVE_DATE}}
**Review:** every 12 months and after every major incident

> Template. Adjust it to your setup before you publish it.

## 1. What counts as an incident

Anything that harms, or could harm, the confidentiality, integrity or availability of our information or
services. Examples: a lost laptop, a leaked password, data sent to the wrong person, an outage, an AI action
that did something nobody approved, suspicious sign-ins.

## 2. Reporting

- Report at once to {{POLICY_OWNER}} or any admin, and record it on the Incidents page in FloBrain.
- Do not try to investigate on your own or delete anything that could be evidence.

## 3. Severity

| Severity | Meaning | First response |
|---|---|---|
| Critical | Customer data exposed, or the service is down for everyone | within 1 hour |
| Major | Limited exposure or a feature down for many people | within 4 hours |
| Minor | No data exposed, small impact | within 1 working day |

## 4. Steps

1. **Assess:** decide if it is an incident and how severe it is. Name one person in charge.
2. **Contain:** stop the harm (revoke a token, pause an account, turn a feature off).
3. **Fix:** remove the cause and restore service and data.
4. **Communicate:** keep updates on the incident record. Tell affected customers without undue delay, and
   regulators where the law requires it (for personal data, often within 72 hours).
5. **Learn:** within 10 working days, write what happened, why, and what changes. Track the actions to the end.

## 5. Evidence

Keep audit log extracts, timelines and decisions with the incident record. Do not change logs.

## 6. Practice

Run a short exercise at least once a year.
