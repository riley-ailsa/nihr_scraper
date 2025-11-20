"""
Score content relevance to determine if it should be indexed.
"""

import re
from typing import Dict, List, Any


class RelevanceScorer:
    """Score webpage content relevance for grant context."""

    # Keywords that indicate grant-relevant content
    GRANT_KEYWORDS = [
        # Funding terms
        'funding', 'grant', 'award', 'budget', 'finance', 'cost',
        'million', 'pounds', '£', 'GBP',

        # Application terms
        'application', 'apply', 'submit', 'deadline', 'closing date',
        'eligibility', 'eligible', 'criteria', 'requirement',

        # Process terms
        'assessment', 'evaluation', 'review', 'selection', 'decision',
        'interview', 'panel', 'committee',

        # Document terms
        'form', 'template', 'guidance', 'specification', 'proposal',

        # Research terms
        'research', 'study', 'project', 'programme', 'collaboration',
        'partnership', 'consortium', 'institution',

        # NIHR/IUK specific
        'NIHR', 'Innovate UK', 'NHS', 'health', 'clinical', 'innovation'
    ]

    # Negative indicators (content probably not relevant)
    NEGATIVE_KEYWORDS = [
        'news', 'blog', 'press release', 'annual report',
        'vacancy', 'job', 'career', 'recruitment',
        'event', 'conference', 'workshop', 'webinar',
        'twitter', 'facebook', 'linkedin', 'social media'
    ]

    def score(self, text: str, source_url: str = "") -> Dict[str, Any]:
        """
        Score content relevance (0-1).

        Returns dict with:
            - score: float (0-1)
            - is_relevant: bool (score > threshold)
            - keyword_matches: List of matched keywords
            - reason: str
        """
        text_lower = text.lower()

        # Count keyword matches
        positive_matches = []
        for keyword in self.GRANT_KEYWORDS:
            if keyword in text_lower:
                positive_matches.append(keyword)

        negative_matches = []
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in text_lower:
                negative_matches.append(keyword)

        # Calculate base score
        positive_score = len(positive_matches) / len(self.GRANT_KEYWORDS)
        negative_score = len(negative_matches) / len(self.NEGATIVE_KEYWORDS)

        # Weighted score
        score = (positive_score * 2) - negative_score
        score = max(0, min(1, score))  # Clamp to 0-1

        # Boost score for high keyword density
        if len(positive_matches) > 10:
            score = min(1, score * 1.5)

        # Determine relevance
        is_relevant = score > 0.3  # Threshold

        # Generate reason
        if is_relevant:
            reason = f"Relevant: {len(positive_matches)} grant keywords found"
        else:
            if negative_matches:
                reason = f"Not relevant: appears to be {negative_matches[0]} content"
            else:
                reason = "Not relevant: insufficient grant-related content"

        return {
            'score': round(score, 2),
            'is_relevant': is_relevant,
            'keyword_matches': positive_matches[:10],  # Top 10
            'reason': reason
        }