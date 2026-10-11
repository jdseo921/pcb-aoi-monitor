-- A1 (REQ-USR-003): a normal start signs in the user who last signed in on the station. Each sign-in with Switch User
-- is an audit entry (user.sign_in, the user's UUID as its object), and the newest one names who signed in last; this
-- index finds it without reading the audit trail back to its first entry, which a workspace where no one has signed
-- in since this migration would otherwise do at every start (REQ-SET-020).

CREATE INDEX audit_action ON audit(action, id);
