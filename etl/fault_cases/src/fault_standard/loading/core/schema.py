"""DDL for PostgreSQL core tables promoted from fault-standard staging data."""

from __future__ import annotations

CORE_SCHEMA = "core"


def table_ref(table_name: str) -> str:
    """Return a schema-qualified core table name."""
    return f"{CORE_SCHEMA}.{table_name}"


CORE_TABLES_IN_DELETE_ORDER = (
    "lane_steps",
    "lane_paths",
    "shared_rule_group_rows",
    "contexts",
    "usage_notes",
    "reference_cases",
    "law_refs",
    "evidence_chunks",
    "adjustment_factors",
    "rule_scenarios",
    "variants",
    "base_faults",
    "rule_parties",
    "rules",
    "rulebooks",
)


def create_core_schema(conn) -> None:
    """Create core schema, tables, and indexes."""
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {CORE_SCHEMA};")

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("core_loads")} (
                load_id BIGSERIAL PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                source_batch_name TEXT NOT NULL,
                load_mode TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("rulebooks")} (
                rulebook_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rulebook_name TEXT,
                source_type TEXT,
                source_subtype TEXT,
                source_file TEXT,
                published_year INTEGER,
                source_reliability TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("rules")} (
                rule_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rulebook_id TEXT NOT NULL REFERENCES {table_ref("rulebooks")}(rulebook_id) ON DELETE CASCADE,
                rule_code TEXT,
                rule_no TEXT,
                rule_title TEXT,
                rule_type TEXT,
                accident_group TEXT,
                accident_subgroup TEXT,
                normalized_ratio TEXT,
                party_a_ratio INTEGER,
                party_b_ratio INTEGER,
                base_fault_type TEXT,
                calculation_source TEXT,
                scenario_required BOOLEAN,
                variants_required BOOLEAN,
                auto_calculation_eligible BOOLEAN,
                page_start INTEGER,
                page_end INTEGER,
                parse_status TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("rule_parties")} (
                party_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT NOT NULL REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                party_key TEXT NOT NULL,
                party_label TEXT,
                party_type TEXT,
                movement TEXT,
                road_position TEXT,
                signal_state TEXT,
                entry_timing TEXT,
                violation_type TEXT,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now(),
                UNIQUE (rule_id, party_key)
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("base_faults")} (
                base_fault_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT NOT NULL UNIQUE REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                base_fault_type TEXT,
                calculation_source TEXT,
                party_a_ratio INTEGER,
                party_b_ratio INTEGER,
                normalized_ratio TEXT,
                scenario_required BOOLEAN,
                variants_required BOOLEAN,
                auto_calculation_eligible BOOLEAN,
                is_one_sided_fault BOOLEAN,
                is_equal_fault BOOLEAN,
                raw_text TEXT,
                quality_flags JSONB,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("variants")} (
                variant_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT NOT NULL REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                variant_key TEXT,
                variant_title TEXT,
                scenario_text TEXT,
                party_a_ratio INTEGER,
                party_b_ratio INTEGER,
                single_party_key TEXT,
                single_party_ratio INTEGER,
                single_party_type TEXT,
                ratio_interpretation TEXT,
                needs_review BOOLEAN,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("rule_scenarios")} (
                scenario_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT NOT NULL REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                scenario_key TEXT,
                scenario_title TEXT,
                scenario_text TEXT,
                party_a_ratio INTEGER,
                party_b_ratio INTEGER,
                single_party_key TEXT,
                single_party_ratio INTEGER,
                single_party_type TEXT,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("adjustment_factors")} (
                adjustment_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT NOT NULL REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                target_party_key TEXT,
                target_party_type TEXT,
                target_party_id TEXT REFERENCES {table_ref("rule_parties")}(party_id) ON DELETE SET NULL,
                factor_name TEXT,
                factor_category TEXT,
                delta INTEGER,
                delta_direction TEXT,
                raw_delta TEXT,
                condition_text TEXT,
                explanation_text TEXT,
                raw_text TEXT,
                is_applicable BOOLEAN,
                auto_calculation_eligible BOOLEAN,
                exclude_from_auto_calculation BOOLEAN,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("evidence_chunks")} (
                chunk_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                block_id TEXT,
                chunk_type TEXT,
                chunk_text TEXT,
                rule_title TEXT,
                accident_group TEXT,
                accident_subgroup TEXT,
                accident_tags JSONB,
                source_reliability TEXT,
                metadata JSONB,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("law_refs")} (
                law_ref_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                law_name TEXT,
                article TEXT,
                clause TEXT,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("reference_cases")} (
                case_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                case_type TEXT,
                case_title TEXT,
                claim_ratio INTEGER,
                respondent_ratio INTEGER,
                fault_ratio_in_case TEXT,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("usage_notes")} (
                usage_note_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                note_type TEXT,
                note_text TEXT,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("contexts")} (
                context_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                context_type TEXT,
                road_area TEXT,
                signal_type TEXT,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("shared_rule_group_rows")} (
                shared_row_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rulebook_id TEXT NOT NULL,
                source_table TEXT,
                shared_group_id TEXT,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                member_rule_id TEXT,
                block_id TEXT,
                chunk_id TEXT,
                law_ref_id TEXT,
                text TEXT,
                metadata JSONB,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("lane_paths")} (
                lane_path_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                party_key TEXT,
                party_id TEXT REFERENCES {table_ref("rule_parties")}(party_id) ON DELETE SET NULL,
                entry_direction TEXT,
                exit_direction TEXT,
                entry_lane TEXT,
                circulation_lane TEXT,
                exit_lane TEXT,
                is_lane_changing BOOLEAN,
                is_exiting BOOLEAN,
                raw_text TEXT,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_ref("lane_steps")} (
                lane_step_id TEXT PRIMARY KEY,
                source_batch_id BIGINT NOT NULL,
                rule_id TEXT REFERENCES {table_ref("rules")}(rule_id) ON DELETE CASCADE,
                rulebook_id TEXT NOT NULL,
                party_key TEXT,
                party_id TEXT REFERENCES {table_ref("rule_parties")}(party_id) ON DELETE SET NULL,
                lane_path_id TEXT REFERENCES {table_ref("lane_paths")}(lane_path_id) ON DELETE SET NULL,
                seq INTEGER,
                movement TEXT,
                lane TEXT,
                direction TEXT,
                source TEXT,
                source_text TEXT,
                confidence DOUBLE PRECISION,
                attributes JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                raw_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT now(),
                updated_at TIMESTAMP DEFAULT now()
            );
            """
        )

        for table_name in CORE_TABLES_IN_DELETE_ORDER:
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_core_{table_name}_source_batch_id ON {table_ref(table_name)} (source_batch_id);")
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_core_{table_name}_rulebook_id ON {table_ref(table_name)} (rulebook_id);")

        for table_name in (
            "rule_parties",
            "base_faults",
            "variants",
            "rule_scenarios",
            "adjustment_factors",
            "evidence_chunks",
            "law_refs",
            "reference_cases",
            "usage_notes",
            "contexts",
            "shared_rule_group_rows",
            "lane_paths",
            "lane_steps",
        ):
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_core_{table_name}_rule_id ON {table_ref(table_name)} (rule_id);")

        cur.execute(
            f"""
            ALTER TABLE {table_ref("adjustment_factors")}
            ADD COLUMN IF NOT EXISTS target_party_id TEXT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {table_ref("lane_paths")}
            ADD COLUMN IF NOT EXISTS party_id TEXT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {table_ref("lane_steps")}
            ADD COLUMN IF NOT EXISTS party_id TEXT;
            """
        )
        cur.execute(
            f"""
            ALTER TABLE {table_ref("lane_steps")}
            ADD COLUMN IF NOT EXISTS lane_path_id TEXT;
            """
        )
        cur.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_core_adjustment_target_party'
                ) THEN
                    ALTER TABLE {table_ref("adjustment_factors")}
                    ADD CONSTRAINT fk_core_adjustment_target_party
                    FOREIGN KEY (target_party_id)
                    REFERENCES {table_ref("rule_parties")}(party_id)
                    ON DELETE SET NULL
                    NOT VALID;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_core_lane_paths_party'
                ) THEN
                    ALTER TABLE {table_ref("lane_paths")}
                    ADD CONSTRAINT fk_core_lane_paths_party
                    FOREIGN KEY (party_id)
                    REFERENCES {table_ref("rule_parties")}(party_id)
                    ON DELETE SET NULL
                    NOT VALID;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_core_lane_steps_party'
                ) THEN
                    ALTER TABLE {table_ref("lane_steps")}
                    ADD CONSTRAINT fk_core_lane_steps_party
                    FOREIGN KEY (party_id)
                    REFERENCES {table_ref("rule_parties")}(party_id)
                    ON DELETE SET NULL
                    NOT VALID;
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'fk_core_lane_steps_lane_path'
                ) THEN
                    ALTER TABLE {table_ref("lane_steps")}
                    ADD CONSTRAINT fk_core_lane_steps_lane_path
                    FOREIGN KEY (lane_path_id)
                    REFERENCES {table_ref("lane_paths")}(lane_path_id)
                    ON DELETE SET NULL
                    NOT VALID;
                END IF;
            END $$;
            """
        )
        # adjustment_factors에는 party_id 컬럼이 없고 target_party_id 컬럼이 있다.
        # 따라서 수정요소 적용 대상 조회용 인덱스는 target_party_id에 생성해야 한다.
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS idx_core_adjustment_factors_target_party_id "
            f"ON {table_ref('adjustment_factors')} (target_party_id);"
        )
        # lane_paths/lane_steps에는 실제 party_id 컬럼이 있으므로 party_id 인덱스를 생성한다.
        for table_name in ("lane_paths", "lane_steps"):
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_core_{table_name}_party_id ON {table_ref(table_name)} (party_id);")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_core_lane_steps_lane_path_id ON {table_ref('lane_steps')} (lane_path_id);")

    conn.commit()
