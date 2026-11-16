-- Business Researcher, R5 (D-72) : resultats ecartes car issus de sites non autorises.
ALTER TABLE research_queries ADD COLUMN blocked_count INTEGER NOT NULL DEFAULT 0;
