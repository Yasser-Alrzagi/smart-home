"""
Enumerations used across all SQLAlchemy models.
Only values defined in the specification are permitted.
"""
import enum


class UserRole(str, enum.Enum):
    student = "Student"
    housing_administration = "Housing Administration"
    student_affairs = "Student Affairs"
    maintenance_officer = "Maintenance Officer"
    activity_officer = "Activity Officer"
    cleaning_officer = "Cleaning Officer"
    food_officer = "Food Officer"
    sports_officer = "Sports Officer"
    system_administrator = "System Administrator"


class AcademicStatus(str, enum.Enum):
    continuing = "Continuing"
    graduating = "Graduating"
    postgraduate = "Postgraduate"
    completed = "Completed"


class HousingStatus(str, enum.Enum):
    active = "Active"
    academic_break = "Academic Break"
    suspended = "Suspended"
    terminated = "Terminated"
    applicant = "Applicant"


class ApplicationStatus(str, enum.Enum):
    draft = "Draft"
    submitted = "Submitted"
    under_review = "Under Review"
    pending_documents = "Pending Documents"
    accepted = "Accepted"
    rejected = "Rejected"
    ready_for_decision = "Ready for Decision"


class RoomStatus(str, enum.Enum):
    available = "Available"
    partially_occupied = "Partially Occupied"
    fully_occupied = "Fully Occupied"
    maintenance = "Maintenance"
    closed = "Closed"


class RoomAssignmentStatus(str, enum.Enum):
    active = "Active"
    ended = "Ended"
    transferred = "Transferred"


class ComplaintStatus(str, enum.Enum):
    open = "Open"
    under_review = "Under Review"
    resolved = "Resolved"
    closed = "Closed"


class MaintenanceStatus(str, enum.Enum):
    pending = "Pending"
    assigned = "Assigned"
    in_progress = "In Progress"
    resolved = "Resolved"
    closed = "Closed"


class CleaningCycleStatus(str, enum.Enum):
    draft = "Draft"
    optimizing = "Optimizing"
    pending_approval = "Pending Approval"
    approved = "Approved"
    active = "Active"
    completed = "Completed"


class CleaningAssignmentStatus(str, enum.Enum):
    pending = "Pending"
    in_progress = "In Progress"
    completed = "Completed"
    skipped = "Skipped"


class PermissionStatus(str, enum.Enum):
    pending = "Pending"
    approved = "Approved"
    rejected = "Rejected"
    cancelled = "Cancelled"


class AbsenceType(str, enum.Enum):
    permission = "Permission"
    emergency = "Emergency"
    unauthorized = "Unauthorized"


class DisciplinaryDecision(str, enum.Enum):
    no_action = "No Action"
    warning = "Warning"
    temporary_suspension = "Temporary Suspension"
    termination = "Termination"
    under_review = "Under Review"


class NotificationStatus(str, enum.Enum):
    unread = "Unread"
    read = "Read"


class AIAlgorithm(str, enum.Enum):
    bfs = "BFS"
    astar = "A*"


class StatusType(str, enum.Enum):
    academic = "Academic"
    housing = "Housing"


class DocumentType(str, enum.Enum):
    national_id = "National ID"
    university_id = "University ID"
    academic_transcript = "Academic Transcript"
    enrollment_certificate = "Enrollment Certificate"
    medical_certificate = "Medical Certificate"
    other = "Other"


# Documents a student must attach before an application may leave Draft.
REQUIRED_DOCUMENT_TYPES = (
    DocumentType.national_id,
    DocumentType.enrollment_certificate,
)


class ServiceType(str, enum.Enum):
    activity = "Activity"
    food = "Food"
    sports = "Sports"
    internet = "Internet"


class ServicePeriodStatus(str, enum.Enum):
    upcoming = "Upcoming"
    open = "Open"
    closed = "Closed"
    completed = "Completed"


class ServiceRegistrationStatus(str, enum.Enum):
    registered = "Registered"
    cancelled = "Cancelled"
    completed = "Completed"


class EmergencyReportStatus(str, enum.Enum):
    reported = "Reported"
    under_review = "Under Review"
    verified = "Verified"
    closed = "Closed"

