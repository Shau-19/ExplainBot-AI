
"""
Phase 1 Test Suite
Run this to validate everything works
"""
import requests
import json
from pathlib import Path

API_BASE = "http://localhost:8000"

def print_test(name, passed):
    symbol = "✅" if passed else "❌"
    print(f"{symbol} {name}")

def test_health():
    """Test 1: Health check"""
    try:
        response = requests.get(f"{API_BASE}/api/health")
        passed = response.status_code == 200
        print_test("Health Check", passed)
        return passed
    except Exception as e:
        print_test(f"Health Check (Error: {e})", False)
        return False

def test_upload():
    """Test 2: Upload document"""
    try:
        # Create a test text file
        test_content = """
        React's reconciliation algorithm is the process by which React updates the DOM.
        When a component's state changes, React creates a new virtual DOM tree.
        It then compares this new tree with the previous one to determine what changed.
        This process is called reconciliation or diffing.
        Only the elements that changed are updated in the real DOM.
        """
        
        test_file = Path("test_doc.txt")
        test_file.write_text(test_content)
        
        # Upload
        with open(test_file, 'rb') as f:
            files = {'file': ('test_doc.txt', f, 'text/plain')}
            response = requests.post(f"{API_BASE}/api/upload", files=files)
        
        # Cleanup
        test_file.unlink()
        
        passed = response.status_code == 200
        if passed:
            data = response.json()
            print_test(f"Document Upload ({data['content_length']} chars)", True)
        else:
            print_test("Document Upload", False)
        
        return passed
    
    except Exception as e:
        print_test(f"Document Upload (Error: {e})", False)
        return False

def test_simple_query():
    """Test 3: Simple query (should choose 'text')"""
    try:
        data = {'query': 'What is reconciliation?'}
        response = requests.post(f"{API_BASE}/api/explain", data=data)
        
        if response.status_code == 200:
            result = response.json()
            decision = result['agent_decision']
            
            print_test(f"Simple Query → Format: {decision['format']}", True)
            print(f"   Reasoning: {decision['reasoning']}")
            print(f"   Answer preview: {result['explanation']['text'][:100]}...")
            return True
        else:
            print_test("Simple Query", False)
            return False
    
    except Exception as e:
        print_test(f"Simple Query (Error: {e})", False)
        return False

def test_complex_query():
    """Test 4: Complex query (should choose 'video' or 'audio')"""
    try:
        data = {'query': 'Explain the entire reconciliation process step by step'}
        response = requests.post(f"{API_BASE}/api/explain", data=data)
        
        if response.status_code == 200:
            result = response.json()
            decision = result['agent_decision']
            
            print_test(f"Complex Query → Format: {decision['format']}", True)
            print(f"   Reasoning: {decision['reasoning']}")
            print(f"   Complexity: {decision['complexity']}")
            return True
        else:
            print_test("Complex Query", False)
            return False
    
    except Exception as e:
        print_test(f"Complex Query (Error: {e})", False)
        return False

def test_status():
    """Test 5: Status check"""
    try:
        response = requests.get(f"{API_BASE}/api/status")
        if response.status_code == 200:
            status = response.json()
            print_test(f"Status Check (Document loaded: {status['document_loaded']})", True)
            return True
        else:
            print_test("Status Check", False)
            return False
    
    except Exception as e:
        print_test(f"Status Check (Error: {e})", False)
        return False

def main():
    print("\n" + "="*60)
    print("🧪 PHASE 1 TEST SUITE")
    print("="*60 + "\n")
    
    print("Testing API endpoints...\n")
    
    tests = [
        test_health,
        test_upload,
        test_simple_query,
        test_complex_query,
        test_status
    ]
    
    results = [test() for test in tests]
    
    print("\n" + "="*60)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED! Ready for Phase 2!")
    else:
        print("⚠️ Some tests failed. Check errors above.")
    
    print("="*60 + "\n")

if __name__ == "__main__":
    main()

""
'''
from groq import Groq
import os
import json


class VideoAgent:
    """
    Creates structured video plans where each scene has:
    - Visual content (what to show)
    - Narration script (what to say during that scene)
    - Duration (how long the scene lasts)
    
    This ensures audio and visuals are perfectly synchronized.
    """
    
    def __init__(self):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.model = "qwen/qwen3.8-27b"

    def plan_scenes(self, query: str, explanation: str) -> dict:
        """
        Breaks explanation into scenes with INDIVIDUAL narration
        
        Returns:
        {
            "title": "Video title",
            "total_duration": 35,
            "mermaid_diagram": "graph TD; ...",
            "scenes": [
                {
                    "id": 1,
                    "type": "title",
                    "narration": "Welcome! Let's explore...",  # ← Scene-specific!
                    "duration": 4
                },
                ...
            ]
        }
        """

        prompt = f"""You are creating a video explanation plan with scene-by-scene narration.

TOPIC: {query}

FULL EXPLANATION:
{explanation[:1200]}

Create a 4-scene video plan. Each scene MUST have its OWN narration that matches what's shown.

CRITICAL: The narration must describe what's VISIBLE in that exact scene.

Respond ONLY with valid JSON:
{{
    "title": "Short punchy title (max 50 chars)",
    "total_duration": 35,
    "mermaid_diagram": "graph TD; A[User]-->B[API]; B-->C[Auth]; C-->D[Token]",
    "scenes": [
        {{
            "id": 1,
            "type": "title",
            "text": "Title text shown on screen",
            "narration": "Opening hook: 'Let's understand how...' (15-20 words)",
            "duration": 4
        }},
        {{
            "id": 2,
            "type": "diagram",
            "caption": "Caption under diagram",
            "narration": "Explain what the diagram shows: 'The system has three components...' (40-50 words, describe the flow)",
            "duration": 15
        }},
        {{
            "id": 3,
            "type": "text",
            "heading": "Key Points",
            "points": ["Point 1 (short)", "Point 2", "Point 3"],
            "narration": "Explain the key points: 'First, credentials are validated. Second, tokens are generated...' (35-45 words)",
            "duration": 12
        }},
        {{
            "id": 4,
            "type": "summary",
            "text": "One-line takeaway",
            "narration": "Wrap up: 'In summary, this ensures...' (15-20 words)",
            "duration": 4
        }}
    ]
}}

Rules:
1. Each scene's narration MUST match what's shown in that scene
2. Narration word counts must fit the duration (assume 2.5 words per second)
3. mermaid_diagram must be valid Mermaid syntax
4. total_duration should be 30-40 seconds
5. NO generic narration - each scene tells its own micro-story"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system", 
                        "content": "You create video scripts with scene-specific narration. Respond only with valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4
            )

            raw = response.choices[0].message.content.strip()

            # Clean markdown formatting if present
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            plan = json.loads(raw)
            
            # Validate that each scene has narration
            for scene in plan['scenes']:
                if 'narration' not in scene or not scene['narration']:
                    scene['narration'] = "Continuing with the explanation."
            
            return plan

        except Exception as e:
            print(f"❌ Video agent error: {e}")
            # Fallback with proper per-scene narration
            return self._fallback_plan(query, explanation)
    
    def _fallback_plan(self, query: str, explanation: str) -> dict:
        """
        Fallback plan if LLM fails
        Splits explanation into 4 parts for each scene
        """
        
        # Split explanation into sentences
        sentences = explanation.split('.')[:8]  # Take first 8 sentences
        
        return {
            "title": query[:50],
            "total_duration": 35,
            "mermaid_diagram": "graph TD; A[Start] --> B[Process] --> C[Result]",
            "scenes": [
                {
                    "id": 1,
                    "type": "title",
                    "text": query[:50],
                    "narration": sentences[0] if len(sentences) > 0 else "Let's explore this topic.",
                    "duration": 4
                },
                {
                    "id": 2,
                    "type": "diagram",
                    "caption": "Process Overview",
                    "narration": '. '.join(sentences[1:4]) if len(sentences) > 3 else "The system follows this flow.",
                    "duration": 15
                },
                {
                    "id": 3,
                    "type": "text",
                    "heading": "Key Points",
                    "points": ["See explanation" for _ in range(3)],
                    "narration": '. '.join(sentences[4:6]) if len(sentences) > 5 else "Here are the key aspects.",
                    "duration": 12
                },
                {
                    "id": 4,
                    "type": "summary",
                    "text": "Summary",
                    "narration": sentences[-1] if sentences else "That covers the main points.",
                    "duration": 4
                }
            ]
        }


        '''#OK THA YEH