-- Eval payloads deliberately have no Object, artifact-index or capture lineage.
CREATE TABLE eval_tests (
 id uuid PRIMARY KEY, revision bigint NOT NULL DEFAULT 1,
 title text NOT NULL, request text NOT NULL, configuration jsonb NOT NULL,
 created_by uuid NOT NULL REFERENCES accounts(id), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE eval_versions (
 test_id uuid NOT NULL REFERENCES eval_tests(id), revision bigint NOT NULL,
 snapshot jsonb NOT NULL, actor_id uuid NOT NULL REFERENCES accounts(id),
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(test_id,revision)
);
CREATE TABLE eval_comparisons (
 id uuid PRIMARY KEY, test_id uuid NOT NULL REFERENCES eval_tests(id),
 test_revision bigint NOT NULL, revision bigint NOT NULL DEFAULT 1,
 snapshot jsonb NOT NULL, context_bundle text NOT NULL,
 created_by uuid NOT NULL REFERENCES accounts(id), created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(test_id,test_revision) REFERENCES eval_versions(test_id,revision)
);
CREATE TABLE eval_attempts (
 id uuid PRIMARY KEY, run_id uuid NOT NULL REFERENCES eval_comparisons(id),
 sequence bigint NOT NULL, arm text NOT NULL CHECK(arm IN ('without','with')),
 payload jsonb NOT NULL, actor_id uuid NOT NULL REFERENCES accounts(id),
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(run_id,sequence)
);
CREATE TABLE eval_receipts (
 credential_id uuid NOT NULL REFERENCES credentials(id), request_key text NOT NULL,
 request_hash text NOT NULL, result jsonb NOT NULL, PRIMARY KEY(credential_id,request_key)
);
-- These capabilities are NOT ordinary credentials: normal actor() rejects them.
CREATE TABLE eval_context_grants (
 secret_hash text PRIMARY KEY, run_id uuid NOT NULL REFERENCES eval_comparisons(id),
 credential_id uuid NOT NULL REFERENCES credentials(id), revoked boolean NOT NULL DEFAULT false,
 expires_at timestamptz NOT NULL DEFAULT now() + interval '24 hours'
);
