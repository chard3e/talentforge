from neo4j import Driver
from app.schemas.cv_extraction import CVExtraction
import uuid
import logging

logger = logging.getLogger(__name__)

class KGLoader:
    """Çıkarılan CV verisini Neo4j Bilgi Grafiği'ne yazar"""

    def __init__(self, driver: Driver):
        self.driver = driver

    def save_candidate(self, extraction: CVExtraction, cv_id: str = None) -> str:
        """Adayı ve ilişkilerini Neo4j'e yazar"""
        if cv_id is None:
            cv_id = str(uuid.uuid4())

        with self.driver.session() as session:
            session.execute_write(self._create_candidate_tx, extraction, cv_id)
        
        logger.info(f"✅ Candidate saved to KG with ID: {cv_id}")
        return cv_id

    def _create_candidate_tx(self, tx, extraction: CVExtraction, cv_id: str):
        """Transaction içinde Cypher sorguları"""
        # Aday düğümü oluştur
        tx.run("""
            MERGE (c:Candidate {id: $cv_id})
            ON CREATE SET c.name = $name, c.email = $email, c.phone = $phone, 
                         c.location = $location, c.summary = $summary, 
                         c.created_at = datetime()
            ON MATCH SET c.updated_at = datetime()
        """, cv_id=cv_id, name=extraction.candidate_name, email=extraction.email, 
             phone=extraction.phone, location=extraction.location, summary=extraction.summary)

        # Deneyimler
        for exp in extraction.experiences:
            exp_id = str(uuid.uuid4())
            display_name = f"{exp.role_title} @ {exp.company_name}"
            tx.run("""
                MATCH (c:Candidate {id: $cv_id})
                MERGE (co:Company {name: $company_name})
                CREATE (e:Experience {id: $exp_id})
                SET e.name = $display_name,
                    e.role_title = $role_title, 
                    e.start_date = $start_date, 
                    e.end_date = $end_date, 
                    e.is_current = $is_current,
                    e.location = $location,
                    e.description = $description
                MERGE (c)-[:HAS_EXPERIENCE]->(e)
                MERGE (e)-[:AT_COMPANY]->(co)
            """, cv_id=cv_id, exp_id=exp_id, display_name=display_name,
                 company_name=exp.company_name, role_title=exp.role_title, 
                 start_date=exp.start_date, end_date=exp.end_date, 
                 is_current=exp.is_current, location=exp.location,
                 description=exp.description)

            # Deneyimde kullanılan yetenekler
            for skill in exp.skills_used:
                tx.run("""
                    MATCH (e:Experience {id: $exp_id})
                    MERGE (s:Skill {name: $skill_name})
                    MERGE (e)-[:USED_SKILL]->(s)
                """, exp_id=exp_id, skill_name=skill)

        # Yetenekler
        for skill in extraction.skills:
            tx.run("""
                MATCH (c:Candidate {id: $cv_id})
                MERGE (s:Skill {name: $skill_name})
                MERGE (c)-[r:HAS_SKILL]->(s)
                SET r.years_experience = $years, r.level = $level, 
                    r.confidence = $confidence, r.category = $category
            """, cv_id=cv_id, skill_name=skill.name, years=skill.years_experience, 
                 level=skill.level, confidence=skill.confidence,
                 category=skill.category)

        # Eğitim
        for edu in extraction.educations:
            edu_id = str(uuid.uuid4())
            display_name = f"{edu.degree} — {edu.field}"
            tx.run("""
                MATCH (c:Candidate {id: $cv_id})
                MERGE (i:Institution {name: $institution})
                CREATE (e:Education {id: $edu_id})
                SET e.name = $display_name,
                    e.degree = $degree, e.field = $field, 
                    e.start_year = $start_year, e.end_year = $end_year,
                    e.gpa = $gpa
                MERGE (c)-[:HAS_EDUCATION]->(e)
                MERGE (e)-[:AT_INSTITUTION]->(i)
            """, cv_id=cv_id, edu_id=edu_id, display_name=display_name,
                 institution=edu.institution, degree=edu.degree, 
                 field=edu.field, start_year=edu.start_year, 
                 end_year=edu.end_year, gpa=edu.gpa)
            
        # Diller
        for lang in (extraction.languages or []):
            tx.run("""
                MATCH (c:Candidate {id: $cv_id})
                MERGE (l:Language {name: $lang})
                MERGE (c)-[:SPEAKS]->(l)
            """, cv_id=cv_id, lang=lang)

        # Sertifikalar
        for cert in (extraction.certifications or []):
            tx.run("""
                MATCH (c:Candidate {id: $cv_id})
                MERGE (ct:Certification {name: $cert})
                MERGE (c)-[:HAS_CERTIFICATION]->(ct)
            """, cv_id=cv_id, cert=cert)

        logger.info(f"✅ Candidate {cv_id} and relationships saved to KG")