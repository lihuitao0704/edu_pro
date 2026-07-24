from statistics import mean


class ChatAnalyticsService:
    @staticmethod
    def aggregate(rows: list, today_sessions: int = 0) -> dict:
        if not rows:
            return {
                "total_sessions": 0, "today_sessions": today_sessions,
                "avg_rating": 0.0, "intent_distribution": {},
                "agent_distribution": {}, "fallback_rate": 0.0,
                "avg_response_time": 0.0,
            }
        intent_distribution = {}
        agent_distribution = {}
        for row in rows:
            intent_distribution[row.intent or "unknown"] = intent_distribution.get(row.intent or "unknown", 0) + int(row.session_count or 0)
            agent_distribution[row.agent_name or "unknown"] = agent_distribution.get(row.agent_name or "unknown", 0) + int(row.turn_count or 0)
        ratings = [float(row.avg_rating) for row in rows if row.avg_rating is not None]
        fallback_rates = [float(row.fallback_rate) for row in rows if row.fallback_rate is not None]
        response_times = [float(row.avg_response_ms) / 1000 for row in rows if row.avg_response_ms is not None]
        return {
            "total_sessions": sum(int(row.session_count or 0) for row in rows),
            "today_sessions": today_sessions,
            "avg_rating": round(mean(ratings), 2) if ratings else 0.0,
            "intent_distribution": intent_distribution,
            "agent_distribution": agent_distribution,
            "fallback_rate": round(mean(fallback_rates), 4) if fallback_rates else 0.0,
            "avg_response_time": round(mean(response_times), 2) if response_times else 0.0,
        }
