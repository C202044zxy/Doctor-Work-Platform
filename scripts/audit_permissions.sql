# Use a migration/admin account to run this script. The runtime account must NOT
# have global or schema-wide privileges (MySQL privileges are additive).
# Replace doctor_runtime, host, database and password before execution.
CREATE USER 'doctor_runtime'@'%' IDENTIFIED BY 'REPLACE_WITH_LOCAL_SECRET';
GRANT SELECT, INSERT ON doctor_platform.audit_logs TO 'doctor_runtime'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON doctor_platform.patients TO 'doctor_runtime'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON doctor_platform.allergies TO 'doctor_runtime'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON doctor_platform.users TO 'doctor_runtime'@'%';
GRANT SELECT ON doctor_platform.departments TO 'doctor_runtime'@'%';
GRANT SELECT ON doctor_platform.roles TO 'doctor_runtime'@'%';
# Add explicit grants for future business tables. Never GRANT ... ON database.*.
GRANT SELECT, INSERT, UPDATE, DELETE ON doctor_platform.temp_grant TO 'doctor_runtime'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON doctor_platform.passkeys TO 'doctor_runtime'@'%';
SHOW GRANTS FOR 'doctor_runtime'@'%';
