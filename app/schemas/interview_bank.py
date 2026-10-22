from pydantic import BaseModel, Field, field_validator


class ImportPreviewRequest(BaseModel):
    raw_text: str = Field(min_length=2, max_length=200_000)
    source_name: str = Field(default="人工粘贴", min_length=1, max_length=500)
    source_locator: str = Field(default="", max_length=2000)
    input_kind: str = Field(default="paste", pattern="^(paste|text_file|docx_file|pdf_file|quark|feishu)$")
    default_company: str = Field(default="", max_length=200)
    default_role: str = Field(default="", max_length=200)


class InterviewQuestionDraft(BaseModel):
    question: str = Field(min_length=2, max_length=5000)
    source: str = Field(min_length=1, max_length=500)
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    question_type: str = Field(default="综合题", max_length=100)
    topic: str = Field(default="产品通识", max_length=200)
    difficulty: str = Field(default="基础", pattern="^(基础|进阶|高阶)$")
    interview_value: int = Field(default=3, ge=1, le=5)
    must_have_points: list[str] = Field(default_factory=list, max_length=20)
    follow_ups: list[str] = Field(default_factory=list, max_length=20)
    answer_framework: list[str] = Field(default_factory=list, max_length=20)
    reference_answer: str = Field(default="", max_length=20_000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    duplicate: bool = False
    duplicate_reason: str = ""

    @field_validator("must_have_points", "follow_ups", "answer_framework", "tags")
    @classmethod
    def clean_string_lists(cls, values: list[str]) -> list[str]:
        return [item.strip()[:300] for item in values if item and item.strip()]


class ImportPreviewResult(BaseModel):
    batch_id: int
    candidates: list[InterviewQuestionDraft]
    candidate_count: int
    duplicate_count: int
    limit: int = 100


class SourceImportRequest(BaseModel):
    source_type: str = Field(pattern="^(quark|feishu)$")
    source_text: str = Field(min_length=8, max_length=4000)
    source_name: str = Field(default="链接导入", min_length=1, max_length=500)
    default_company: str = Field(default="", max_length=200)
    default_role: str = Field(default="", max_length=200)
    max_questions: int = Field(default=100, ge=1, le=100)
    max_scrolls: int = Field(default=100, ge=1, le=200)


class SourceImportResult(BaseModel):
    status: str
    source_type: str
    message: str
    input_kind: str = ""
    source_locator: str = ""
    raw_text: str = ""
    character_count: int = 0
    scroll_count: int = 0
    resumed_from: int = 0
    stop_reason: str = ""
    batch_id: int | None = None
    candidates: list[InterviewQuestionDraft] = Field(default_factory=list)
    candidate_count: int = 0
    duplicate_count: int = 0


class DocumentExtractionResult(BaseModel):
    filename: str
    input_kind: str
    raw_text: str
    character_count: int


class ImportCommitRequest(BaseModel):
    batch_id: int
    questions: list[InterviewQuestionDraft] = Field(min_length=1, max_length=100)


class ImportCommitResult(BaseModel):
    batch_id: int
    inserted_count: int
    duplicate_count: int
    question_ids: list[int]


class InterviewQuestionItem(InterviewQuestionDraft):
    id: int
    import_batch_id: int
    knowledge_point_id: int | None = None
    times_used: int = 0


class ImportRollbackResult(BaseModel):
    batch_id: int
    removed_count: int
    status: str
