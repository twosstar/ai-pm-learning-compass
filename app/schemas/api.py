from pydantic import BaseModel, Field, HttpUrl, field_validator


class BrowserStatus(BaseModel):
    connected: bool
    page_count: int = 0
    message: str
    cdp_url: str = "http://127.0.0.1:9222"
    cdp_available: bool = False
    websocket_url: str = ""
    browser_type: str = ""
    browser_executable: str = ""
    browser_pid: int | None = None
    profile_path: str = ""
    launch_attempted: bool = False
    launch_error: str = ""


class CrawlRequest(BaseModel):
    course_name: str = Field(min_length=1, max_length=300)
    start_url: HttpUrl
    max_pages: int | None = Field(default=None, ge=1, le=500)
    restart: bool = False

    @field_validator("start_url")
    @classmethod
    def reject_embedded_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("课程 URL 不得包含用户名或密码。")
        return value


class CrawlResult(BaseModel):
    course_id: int
    pages_saved: int
    pages_skipped: int
    pages_processed: int
    total_visited: int
    pending_pages: int
    completed: bool
    errors: list[str]


class StudyQuestion(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    course_id: int | None = None
    lesson_id: int | None = None


class SourceItem(BaseModel):
    lesson_id: int
    title: str
    url: str


class StudyAnswer(BaseModel):
    answer: str
    sources: list[SourceItem]


class LessonItem(BaseModel):
    id: int
    title: str
    url: str


class CourseDeleteResult(BaseModel):
    course_id: int
    course_name: str
    lessons_deleted: int


class LessonStudyStart(BaseModel):
    lesson_id: int | None = None
    course_id: int | None = None
    scope_type: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section_id: str | None = None


class LessonStudyStarted(BaseModel):
    session_id: int
    lesson_title: str
    summary: str
    key_points: list[str]
    question: str


class LessonStudyAnswer(BaseModel):
    session_id: int
    answer: str = Field(min_length=1, max_length=10000)


class LessonStudyFeedback(BaseModel):
    score: int = Field(ge=0, le=100)
    mastery_score: int = Field(ge=0, le=100)
    feedback: str
    strengths: list[str]
    gaps: list[str]
    reference_answer: str
    next_question: str | None
    answered_count: int
    completed: bool


class InterviewStart(BaseModel):
    role_level: str = Field(default="中级产品经理", max_length=100)
    focus: str = Field(default="综合产品能力", max_length=300)


class InterviewStarted(BaseModel):
    session_id: int
    question: str


class InterviewAnswer(BaseModel):
    session_id: int
    answer: str = Field(min_length=1, max_length=10000)
    answer_mode: str = "text"
    transcript: str | None = None
    edited_transcript: str | None = None
    audio_duration: float | None = None


class InterviewFeedback(BaseModel):
    feedback: str
    next_question: str
    actual_global_interview_readiness: int = 0
