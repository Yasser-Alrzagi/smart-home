-- Offline preview of revision ca98ebed8d42 upgrade(), in the exact order the
-- migration emits it. Produced by replaying the migration file op calls against
-- the MySQL dialect. NOT executed against any database.

CREATE TABLE floors (
	floor_id VARCHAR(36) NOT NULL, 
	floor_number VARCHAR(20) NOT NULL, 
	building_name VARCHAR(100) NOT NULL, 
	PRIMARY KEY (floor_id), 
	CONSTRAINT uq_floors_building_number UNIQUE (building_name, floor_number)
);
CREATE TABLE services (
	service_id VARCHAR(36) NOT NULL, 
	service_type ENUM('activity','food','sports','internet') NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	managed_by_role ENUM('student','housing_administration','student_affairs','maintenance_officer','activity_officer','cleaning_officer','food_officer','sports_officer','system_administrator') NOT NULL, 
	is_active BOOL NOT NULL, 
	PRIMARY KEY (service_id)
);
CREATE TABLE users (
	user_id VARCHAR(36) NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` ENUM('student','housing_administration','student_affairs','maintenance_officer','activity_officer','cleaning_officer','food_officer','sports_officer','system_administrator') NOT NULL, 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id)
);
CREATE UNIQUE INDEX ix_users_email ON users (email);
CREATE UNIQUE INDEX ix_users_username ON users (username);
CREATE TABLE apartments (
	apartment_id VARCHAR(36) NOT NULL, 
	floor_id VARCHAR(36) NOT NULL, 
	apartment_number VARCHAR(20) NOT NULL, 
	PRIMARY KEY (apartment_id), 
	FOREIGN KEY(floor_id) REFERENCES floors (floor_id) ON DELETE RESTRICT, 
	CONSTRAINT uq_apartments_floor_number UNIQUE (floor_id, apartment_number)
);
CREATE INDEX ix_apartments_floor_id ON apartments (floor_id);
CREATE TABLE cleaning_cycles (
	cycle_id VARCHAR(36) NOT NULL, 
	floor_id VARCHAR(36) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	status ENUM('draft','optimizing','pending_approval','approved','active','completed') NOT NULL, 
	created_by VARCHAR(36), 
	PRIMARY KEY (cycle_id), 
	FOREIGN KEY(created_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(floor_id) REFERENCES floors (floor_id) ON DELETE RESTRICT
);
CREATE INDEX ix_cleaning_cycles_floor_id ON cleaning_cycles (floor_id);
CREATE TABLE notifications (
	notification_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	message TEXT NOT NULL, 
	status ENUM('unread','read') NOT NULL, 
	created_at DATETIME NOT NULL, 
	read_at DATETIME, 
	PRIMARY KEY (notification_id), 
	FOREIGN KEY(user_id) REFERENCES users (user_id) ON DELETE CASCADE
);
CREATE INDEX ix_notifications_user_id ON notifications (user_id);
CREATE TABLE service_periods (
	period_id VARCHAR(36) NOT NULL, 
	service_id VARCHAR(36) NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	capacity INTEGER, 
	status ENUM('upcoming','open','closed','completed') NOT NULL, 
	PRIMARY KEY (period_id), 
	FOREIGN KEY(service_id) REFERENCES services (service_id) ON DELETE CASCADE
);
CREATE INDEX ix_service_periods_service_id ON service_periods (service_id);
CREATE TABLE students (
	student_id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	full_name VARCHAR(200) NOT NULL, 
	university VARCHAR(200) NOT NULL, 
	major VARCHAR(200) NOT NULL, 
	academic_status ENUM('continuing','graduating','postgraduate','completed') NOT NULL, 
	housing_status ENUM('active','academic_break','suspended','terminated') NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (student_id), 
	FOREIGN KEY(user_id) REFERENCES users (user_id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX ix_students_user_id ON students (user_id);
CREATE TABLE ai_optimization_runs (
	run_id VARCHAR(36) NOT NULL, 
	cycle_id VARCHAR(36) NOT NULL, 
	algorithm ENUM('bfs','astar') NOT NULL, 
	total_cost FLOAT, 
	fairness_score FLOAT, 
	feasibility_rate FLOAT, 
	nodes_expanded INTEGER, 
	execution_time FLOAT, 
	result_summary TEXT, 
	approved_by VARCHAR(36), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (run_id), 
	FOREIGN KEY(approved_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(cycle_id) REFERENCES cleaning_cycles (cycle_id) ON DELETE CASCADE
);
CREATE INDEX ix_ai_optimization_runs_cycle_id ON ai_optimization_runs (cycle_id);
CREATE TABLE applications (
	application_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	application_date DATETIME NOT NULL, 
	status ENUM('draft','submitted','under_review','pending_documents','accepted','rejected') NOT NULL, 
	decision_date DATETIME, 
	decision_notes TEXT, 
	reviewed_by VARCHAR(36), 
	PRIMARY KEY (application_id), 
	FOREIGN KEY(reviewed_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_applications_student_id ON applications (student_id);
CREATE TABLE cleaning_assignments (
	assignment_id VARCHAR(36) NOT NULL, 
	cycle_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	task_description VARCHAR(500) NOT NULL, 
	assignment_date DATE NOT NULL, 
	status ENUM('pending','in_progress','completed','skipped') NOT NULL, 
	completed_date DATETIME, 
	PRIMARY KEY (assignment_id), 
	FOREIGN KEY(cycle_id) REFERENCES cleaning_cycles (cycle_id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_cleaning_assignments_cycle_id ON cleaning_assignments (cycle_id);
CREATE INDEX ix_cleaning_assignments_student_id ON cleaning_assignments (student_id);
CREATE TABLE complaints (
	complaint_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	category VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	status ENUM('open','under_review','resolved','closed') NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	handled_by VARCHAR(36), 
	resolution TEXT, 
	PRIMARY KEY (complaint_id), 
	FOREIGN KEY(handled_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_complaints_student_id ON complaints (student_id);
CREATE TABLE disciplinary_cases (
	case_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	incident_date DATE NOT NULL, 
	description TEXT NOT NULL, 
	decision ENUM('no_action','warning','temporary_suspension','termination','under_review') NOT NULL, 
	start_date DATE, 
	end_date DATE, 
	decided_by VARCHAR(36), 
	PRIMARY KEY (case_id), 
	FOREIGN KEY(decided_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_disciplinary_cases_student_id ON disciplinary_cases (student_id);
CREATE TABLE permission_requests (
	permission_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	status ENUM('pending','approved','rejected','cancelled') NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE NOT NULL, 
	reason TEXT NOT NULL, 
	reviewed_by VARCHAR(36), 
	PRIMARY KEY (permission_id), 
	FOREIGN KEY(reviewed_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_permission_requests_student_id ON permission_requests (student_id);
CREATE TABLE rooms (
	room_id VARCHAR(36) NOT NULL, 
	apartment_id VARCHAR(36) NOT NULL, 
	room_number VARCHAR(20) NOT NULL, 
	capacity INTEGER NOT NULL, 
	status ENUM('available','partially_occupied','fully_occupied','maintenance','closed') NOT NULL, 
	PRIMARY KEY (room_id), 
	FOREIGN KEY(apartment_id) REFERENCES apartments (apartment_id) ON DELETE RESTRICT
);
CREATE INDEX ix_rooms_apartment_id ON rooms (apartment_id);
CREATE TABLE service_registrations (
	registration_id VARCHAR(36) NOT NULL, 
	period_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	registered_at DATETIME NOT NULL, 
	status ENUM('registered','cancelled','completed') NOT NULL, 
	PRIMARY KEY (registration_id), 
	FOREIGN KEY(period_id) REFERENCES service_periods (period_id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE, 
	CONSTRAINT uq_service_registrations_period_student UNIQUE (period_id, student_id)
);
CREATE INDEX ix_service_registrations_period_id ON service_registrations (period_id);
CREATE INDEX ix_service_registrations_student_id ON service_registrations (student_id);
CREATE TABLE student_absences (
	absence_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	absence_type ENUM('permission','emergency','unauthorized') NOT NULL, 
	start_date DATE NOT NULL, 
	end_date DATE, 
	source VARCHAR(200), 
	notes TEXT, 
	PRIMARY KEY (absence_id), 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_student_absences_student_id ON student_absences (student_id);
CREATE TABLE student_status_history (
	history_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	status_type ENUM('academic','housing') NOT NULL, 
	old_status VARCHAR(50), 
	new_status VARCHAR(50) NOT NULL, 
	start_date DATETIME NOT NULL, 
	end_date DATETIME, 
	changed_by VARCHAR(36), 
	notes TEXT, 
	PRIMARY KEY (history_id), 
	FOREIGN KEY(changed_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_student_status_history_student_id ON student_status_history (student_id);
CREATE TABLE application_documents (
	document_id VARCHAR(36) NOT NULL, 
	application_id VARCHAR(36) NOT NULL, 
	document_type ENUM('national_id','university_id','academic_transcript','enrollment_certificate','medical_certificate','other') NOT NULL, 
	file_path VARCHAR(500) NOT NULL, 
	uploaded_at DATETIME NOT NULL, 
	PRIMARY KEY (document_id), 
	FOREIGN KEY(application_id) REFERENCES applications (application_id) ON DELETE CASCADE
);
CREATE INDEX ix_application_documents_application_id ON application_documents (application_id);
CREATE TABLE emergency_reports (
	report_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	reported_at DATETIME NOT NULL, 
	description TEXT NOT NULL, 
	status ENUM('reported','under_review','verified','closed') NOT NULL, 
	exit_verified BOOL NOT NULL, 
	absence_id VARCHAR(36), 
	handled_by VARCHAR(36), 
	PRIMARY KEY (report_id), 
	FOREIGN KEY(absence_id) REFERENCES student_absences (absence_id) ON DELETE SET NULL, 
	FOREIGN KEY(handled_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_emergency_reports_absence_id ON emergency_reports (absence_id);
CREATE INDEX ix_emergency_reports_student_id ON emergency_reports (student_id);
CREATE TABLE maintenance_requests (
	request_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	room_id VARCHAR(36), 
	problem_type VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	status ENUM('pending','assigned','in_progress','resolved','closed') NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	handled_by VARCHAR(36), 
	resolution TEXT, 
	PRIMARY KEY (request_id), 
	FOREIGN KEY(handled_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(room_id) REFERENCES rooms (room_id) ON DELETE SET NULL, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_maintenance_requests_room_id ON maintenance_requests (room_id);
CREATE INDEX ix_maintenance_requests_student_id ON maintenance_requests (student_id);
CREATE TABLE room_assignments (
	assignment_id VARCHAR(36) NOT NULL, 
	student_id VARCHAR(36) NOT NULL, 
	room_id VARCHAR(36) NOT NULL, 
	assignment_date DATETIME NOT NULL, 
	end_date DATETIME, 
	status ENUM('active','ended','transferred') NOT NULL, 
	assigned_by VARCHAR(36), 
	PRIMARY KEY (assignment_id), 
	FOREIGN KEY(assigned_by) REFERENCES users (user_id) ON DELETE SET NULL, 
	FOREIGN KEY(room_id) REFERENCES rooms (room_id) ON DELETE CASCADE, 
	FOREIGN KEY(student_id) REFERENCES students (student_id) ON DELETE CASCADE
);
CREATE INDEX ix_room_assignments_room_id ON room_assignments (room_id);
CREATE INDEX ix_room_assignments_student_id ON room_assignments (student_id);
