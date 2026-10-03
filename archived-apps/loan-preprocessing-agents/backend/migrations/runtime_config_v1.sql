-- Execute as a dedicated non-runtime schema owner. Provision login grants separately.
CREATE SCHEMA runtime_config;
REVOKE ALL ON SCHEMA runtime_config FROM PUBLIC;
CREATE TABLE runtime_config.principals (
  role_name name NOT NULL,
  environment text NOT NULL,
  application text NOT NULL CHECK (application IN ('dsce', 'loan')),
  can_write boolean NOT NULL DEFAULT false,
  PRIMARY KEY (role_name, environment, application)
);
CREATE TABLE runtime_config.revisions (
  environment text NOT NULL,
  application text NOT NULL CHECK (application IN ('dsce', 'loan')),
  group_name text NOT NULL,
  revision uuid NOT NULL,
  schema_version integer NOT NULL CHECK (schema_version = 1),
  key_id text NOT NULL,
  nonce bytea NOT NULL CHECK (octet_length(nonce) = 12),
  ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) >= 16),
  actor name NOT NULL DEFAULT session_user CHECK (actor = session_user),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (environment, application, group_name, revision),
  UNIQUE (application, key_id, nonce)
);
CREATE TABLE runtime_config.active (
  environment text NOT NULL,
  application text NOT NULL,
  group_name text NOT NULL,
  revision uuid NOT NULL,
  PRIMARY KEY (environment, application, group_name),
  FOREIGN KEY (environment, application, group_name, revision)
    REFERENCES runtime_config.revisions(environment, application, group_name, revision)
);
CREATE TABLE runtime_config.audit (
  event_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  environment text NOT NULL,
  application text NOT NULL,
  group_name text NOT NULL,
  previous_revision uuid,
  revision uuid NOT NULL,
  actor name NOT NULL DEFAULT session_user,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE runtime_config.principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_config.principals FORCE ROW LEVEL SECURITY;
CREATE POLICY own_principal ON runtime_config.principals FOR SELECT USING (role_name = session_user);
ALTER TABLE runtime_config.revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_config.revisions FORCE ROW LEVEL SECURITY;
ALTER TABLE runtime_config.active ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_config.active FORCE ROW LEVEL SECURITY;
ALTER TABLE runtime_config.audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_config.audit FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped_read ON runtime_config.revisions FOR SELECT USING (
  EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=revisions.environment AND p.application=revisions.application)
);
CREATE POLICY scoped_insert ON runtime_config.revisions FOR INSERT WITH CHECK (
  EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=revisions.environment AND p.application=revisions.application AND p.can_write)
);
CREATE POLICY scoped_read ON runtime_config.active FOR SELECT USING (
  EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=active.environment AND p.application=active.application)
);
CREATE POLICY scoped_insert ON runtime_config.active FOR INSERT WITH CHECK (
  EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=active.environment AND p.application=active.application AND p.can_write)
);
CREATE POLICY scoped_update ON runtime_config.active FOR UPDATE USING (
  EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=active.environment AND p.application=active.application AND p.can_write)
) WITH CHECK (
  EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=active.environment AND p.application=active.application AND p.can_write)
);
CREATE POLICY scoped_read ON runtime_config.audit FOR SELECT USING (
  EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=audit.environment AND p.application=audit.application)
);
CREATE POLICY scoped_insert ON runtime_config.audit FOR INSERT WITH CHECK (
  actor=session_user AND EXISTS (SELECT 1 FROM runtime_config.principals p WHERE p.role_name=session_user AND p.environment=audit.environment AND p.application=audit.application AND p.can_write)
);
CREATE FUNCTION runtime_config.record_activation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, runtime_config AS $$
BEGIN
  INSERT INTO runtime_config.audit(environment,application,group_name,previous_revision,revision,actor)
  VALUES (NEW.environment, NEW.application, NEW.group_name,
          CASE WHEN TG_OP = 'UPDATE' THEN OLD.revision ELSE NULL END, NEW.revision, session_user);
  RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION runtime_config.record_activation() FROM PUBLIC;
CREATE TRIGGER activation_audit AFTER INSERT OR UPDATE ON runtime_config.active
FOR EACH ROW EXECUTE FUNCTION runtime_config.record_activation();
REVOKE ALL ON ALL TABLES IN SCHEMA runtime_config FROM PUBLIC;
