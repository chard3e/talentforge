from typing import List, Dict, Any
import logging
from neo4j import Driver
from app.schemas.query import QuerySpec

logger = logging.getLogger(__name__)

class CandidateMatcher:
    """İK sorgusuna göre adayları skorlayarak bulan matcher"""

    def __init__(self, driver: Driver):
        self.driver = driver

    def search(self, query: QuerySpec, limit: int = 10) -> List[Dict[str, Any]]:
        """Esnek hybrid sorgu ile adayları bulur ve skorlar"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (c:Candidate)
                OPTIONAL MATCH (c)-[r:HAS_SKILL]->(s:Skill)
                OPTIONAL MATCH (c)-[:HAS_EXPERIENCE]->(e:Experience)
                
                WITH c, 
                     collect(s.name) as skills,
                     count(e) as experience_count
                
                WITH c, skills, experience_count,
                     size([s IN skills WHERE s IN $must_skills]) as must_match,
                     size($must_skills) as must_total
                
                WITH c, skills, experience_count,
                     CASE 
                        WHEN must_total = 0 THEN 1.0 
                        ELSE toFloat(must_match) / must_total 
                     END as skill_score
                
                RETURN 
                    c.name as name,
                    c.email as email,
                    skills,
                    experience_count,
                    skill_score * 100 as match_percentage,
                    'Skill match: ' + toString(skill_score * 100) + '%' as reason
                
                ORDER BY skill_score DESC, experience_count DESC
                LIMIT $limit
            """, must_skills=query.must_have_skills or [], limit=limit)
            
            return [record.data() for record in result]