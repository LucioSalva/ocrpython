"""initial schema: templates, documents, document_pages, cfdi_extractions

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-28
"""
from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


TEMPLATE_SEED = [
    {
        "code": "texto_libre",
        "name": "Texto libre",
        "fields": [],
    },
    {
        "code": "factura_generica",
        "name": "Factura genérica",
        "fields": [
            {"key": "rfc_emisor", "label": "RFC emisor", "type": "string"},
            {"key": "rfc_receptor", "label": "RFC receptor", "type": "string"},
            {"key": "folio", "label": "Folio", "type": "string"},
            {"key": "total", "label": "Total", "type": "number"},
            {"key": "iva", "label": "IVA", "type": "number"},
        ],
    },
    {
        "code": "ine",
        "name": "INE",
        "fields": [
            {"key": "nombre", "label": "Nombre", "type": "string"},
            {"key": "curp", "label": "CURP", "type": "string"},
            {"key": "vigencia", "label": "Vigencia", "type": "string"},
        ],
    },
]


def upgrade() -> None:
    # Required extensions (unaccent + spanish_unaccent config are also installed
    # by db/init/001_extensions.sql; pgcrypto is needed for gen_random_uuid()).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_ts_config WHERE cfgname = 'spanish_unaccent'
            ) THEN
                EXECUTE 'CREATE TEXT SEARCH CONFIGURATION spanish_unaccent ( COPY = spanish )';
                EXECUTE 'ALTER TEXT SEARCH CONFIGURATION spanish_unaccent
                         ALTER MAPPING FOR
                            hword, hword_part, word, asciiword, asciihword, hword_asciipart
                         WITH unaccent, spanish_stem';
            END IF;
        END
        $$;
        """
    )

    # --- templates ---
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index("ix_templates_code", "templates", ["code"], unique=True)

    # --- documents ---
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=2), nullable=True),
        sa.Column("is_native_pdf", sa.Boolean(), nullable=True),
        sa.Column("ocr_engine", sa.String(length=32), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column("extracted_fields", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "text_search",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('spanish_unaccent', coalesce(text_content,''))",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index(
        "ix_documents_text_search",
        "documents",
        ["text_search"],
        postgresql_using="gin",
    )
    op.create_index("ix_documents_created_at", "documents", ["created_at"])

    # --- document_pages ---
    op.create_table(
        "document_pages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column(
            "text_search",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('spanish_unaccent', coalesce(text_content,''))",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_pages_document_id", "document_pages", ["document_id"]
    )
    op.create_index(
        "ix_document_pages_text_search",
        "document_pages",
        ["text_search"],
        postgresql_using="gin",
    )

    # --- cfdi_extractions ---
    op.create_table(
        "cfdi_extractions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uuid_sat", sa.String(length=36), nullable=False, unique=True),
        sa.Column("rfc_emisor", sa.String(length=13), nullable=True),
        sa.Column("rfc_receptor", sa.String(length=13), nullable=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=True),
        sa.Column("subtotal", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_iva", sa.Numeric(14, 2), nullable=True),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=True),
        sa.Column("serie", sa.String(length=64), nullable=True),
        sa.Column("folio", sa.String(length=64), nullable=True),
        sa.Column("raw_xml", sa.Text(), nullable=True),
    )
    op.create_index("ix_cfdi_extractions_uuid_sat", "cfdi_extractions", ["uuid_sat"], unique=True)
    op.create_index("ix_cfdi_extractions_document_id", "cfdi_extractions", ["document_id"])

    # --- Seed templates ---
    bind = op.get_bind()
    for tpl in TEMPLATE_SEED:
        bind.execute(
            sa.text(
                "INSERT INTO templates (code, name, fields) "
                "VALUES (:code, :name, CAST(:fields AS JSONB)) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "code": tpl["code"],
                "name": tpl["name"],
                "fields": json.dumps(tpl["fields"], ensure_ascii=False),
            },
        )


def downgrade() -> None:
    op.drop_index("ix_cfdi_extractions_document_id", table_name="cfdi_extractions")
    op.drop_index("ix_cfdi_extractions_uuid_sat", table_name="cfdi_extractions")
    op.drop_table("cfdi_extractions")

    op.drop_index("ix_document_pages_text_search", table_name="document_pages")
    op.drop_index("ix_document_pages_document_id", table_name="document_pages")
    op.drop_table("document_pages")

    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_index("ix_documents_text_search", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_templates_code", table_name="templates")
    op.drop_table("templates")
