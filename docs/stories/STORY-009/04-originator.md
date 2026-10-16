# 04: The Originator sees and resubmits requests made for them

Status: ready-for-agent
Triage: ready-for-agent
Parent: STORY-009
Blocked by: 02

**What to build:** "My requests" also lists, in every status, the requests
where the Account is the Originator, labelled "ขอแทนโดย <Requester name>". An
Originator whose Account is active and in the request's Plant (if the Account
has a Plant) can resubmit a Needs Info request exactly like the Requester,
except that the originator fields are locked for them. The Requester can still
change the originator fields on resubmit; they are validated exactly as on a
new request. See decisions.md 2026-10-16.

- [ ] An Originator sees their requests in "My requests" with the label
- [ ] An Originator resubmits a Needs Info request; the actor on the events is
      their email
- [ ] An Originator Account that is inactive, or in another Plant → 403
- [ ] Originator fields posted by the Originator are ignored
- [ ] The Requester changing the originator email to a domain that is not
      allowed → Thai error, nothing saved
