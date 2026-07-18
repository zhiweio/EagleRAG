"""Rule-based biomed content classifiers (ingest-side, G15/P1-9)."""

from __future__ import annotations

import re

from eagle_rag.config import get_settings
from eagle_rag.plugins.classifier import ClassificationContext, ClassificationDecision

__all__ = ["BiomedImageClassifier", "BiomedTextClassifier"]

_BIOMED_TERM_RE = re.compile(
    r"\b("
    r"HER2|ERBB2|SMILES|InChI|kinase|pathway|receptor|mutation|"
    r"oncogene|phosphorylation|inhibitor|ligand|compound|"
    r"CT\b|MRI|ultrasound|H&E|histopathology|biopsy"
    r")\b",
    re.IGNORECASE,
)
_SMILES_RE = re.compile(r"(InChI=|SMILES\b|C\(=O\)|\[[A-Z][a-z]?@?\])", re.IGNORECASE)
_RADIOLOGY_RE = re.compile(
    r"\b(CT scan|computed tomography|MRI|magnetic resonance|ultrasound|radiograph)\b",
    re.IGNORECASE,
)
_PATHOLOGY_RE = re.compile(
    r"\b(H&E|hematoxylin|histopathology|biopsy|dysplasia|immunohistochemistry)\b",
    re.IGNORECASE,
)
_CHEMICAL_IMAGE_RE = re.compile(r"\b(SMILES|molfile|compound structure|chemical structure)\b", re.I)


class BiomedTextClassifier:
    """Route text chunks to general or biomed-specialized text collections."""

    def classify(self, ctx: ClassificationContext) -> ClassificationDecision | None:
        if ctx.modality != "text":
            return None
        text = ctx.content if isinstance(ctx.content, str) else ""
        if not text.strip():
            return None

        settings = get_settings()
        if _BIOMED_TERM_RE.search(text):
            return ClassificationDecision(
                category="biomed_term",
                target_collection="eagle_text_biomed",
                target_encoder="pubmedbert",
                chunk_type="biomed_text",
                confidence=0.75,
                exclusive_group="biomed_text",
                metadata={"rule": "biomed_term_keyword"},
            )

        if _SMILES_RE.search(text):
            return ClassificationDecision(
                category="chemical_text",
                target_collection="eagle_chemical",
                target_encoder="molformer",
                chunk_type="chemical",
                confidence=0.7,
                exclusive_group="biomed_text",
                metadata={"rule": "smiles_or_chemical_token"},
            )

        section = str(ctx.extra.get("section", "")).lower()
        if section in {"methods", "results"} and len(text.split()) >= 40:
            return ClassificationDecision(
                category="biomed_term",
                target_collection="eagle_text_biomed",
                target_encoder="pubmedbert",
                chunk_type="biomed_text",
                confidence=0.6,
                exclusive_group="biomed_text",
                metadata={"rule": "imrad_methods_results"},
            )

        return ClassificationDecision(
            category="general_text",
            target_collection=settings.milvus.text_collection,
            target_encoder="text-embedding-v4",
            chunk_type="text",
            confidence=0.55,
            metadata={"rule": "biomed_default_text"},
        )


class BiomedImageClassifier:
    """Route visual assets to biomed or core visual collections."""

    def classify(self, ctx: ClassificationContext) -> ClassificationDecision | None:
        if ctx.modality != "visual":
            return None

        settings = get_settings()
        hint = " ".join(
            str(v)
            for v in (
                ctx.extra.get("caption", ""),
                ctx.extra.get("alt_text", ""),
                ctx.extra.get("content_summary", ""),
                ctx.parent_section,
            )
            if v
        )

        if _RADIOLOGY_RE.search(hint) or str(ctx.extra.get("modality", "")).lower() in {
            "ct",
            "mri",
            "ultrasound",
            "radiology",
        }:
            return ClassificationDecision(
                category="radiology_image",
                target_collection="eagle_medical_radiology",
                target_encoder="medimageinsight",
                chunk_type="medical_image",
                confidence=0.8,
                metadata={"rule": "radiology_keyword"},
            )

        if _PATHOLOGY_RE.search(hint) or str(ctx.extra.get("modality", "")).lower() in {
            "pathology",
            "histology",
            "he",
        }:
            return ClassificationDecision(
                category="pathology_slide",
                target_collection="eagle_medical_pathology",
                target_encoder="uni2",
                chunk_type="medical_image",
                confidence=0.8,
                metadata={"rule": "pathology_keyword"},
            )

        if _CHEMICAL_IMAGE_RE.search(hint) or ctx.file_ext.lower() in {".mol", ".sdf", ".pdb"}:
            return ClassificationDecision(
                category="chemical",
                target_collection="eagle_chemical",
                target_encoder="molformer",
                chunk_type="chemical",
                confidence=0.75,
                metadata={"rule": "chemical_image_or_ext"},
            )

        if ctx.file_ext.lower() in {".dcm", ".nii", ".nii.gz"}:
            return ClassificationDecision(
                category="radiology_image",
                target_collection="eagle_medical_radiology",
                target_encoder="medimageinsight",
                chunk_type="medical_image",
                confidence=0.85,
                metadata={"rule": "radiology_file_ext"},
            )

        return ClassificationDecision(
            category="document_visual",
            target_collection=settings.milvus.visual_collection,
            target_encoder="qwen3-vl",
            chunk_type="image",
            confidence=0.5,
            metadata={"rule": "biomed_document_visual_fallback"},
        )
