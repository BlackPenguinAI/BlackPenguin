-- Initialized only in the fresh disposable Compose database.
CREATE TABLE hei06a_test_guard (purpose text PRIMARY KEY);
INSERT INTO hei06a_test_guard VALUES ('hei06a-disposable-synthetic-only-v1');
CREATE TABLE hei06a_test_inference (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
