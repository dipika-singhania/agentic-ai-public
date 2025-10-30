def planner_agent(user_prompt: str, model_id: str = "openai:o4-mini") -> List[str]:
    planner_agent_prompt = f"""
You are a planning agent responsible for organizing a regulatory compliance analysis workflow using multiple intelligent agents.

🧠 Available agents:
- Research agent: MUST begin with a broad **web search using Tavily** to identify only **relevant** and **authoritative** items (e.g., goverment regulatory guidelines, official regulations databases, official brand websites, amazon related announcents**). The output MUST capture for each regulations: name, official_authority, regulations_requirements, URL , and (if available) DOI.
- Research agent: AFTER the Tavily step, perform **targeted/official website search** for the candidates discovered in the web step. If exact policy( or recall or brand-infringemnt or safety URL) is present, record its URL, extract the specific information required from the URL.
- Writer agent: Drafts based on research findings. Will draft the entire markdown with output json embedded inside based on extracting informations necessary from previous steps.
- Editor agent: reviews, reflects on, and improves(revise) drafts. Additionally provides feedback by critical verification of each statement in output json. Flags out incorrect/incomplete information which might require further research. 


🎯 Key Analysis Requirements:
- **Multi-modal**: Analyze both text content (title, description, bullets) AND product images
- **Cross-consistency**: Check alignment between text descriptions and visual content in images
- **Image analysis**: Extract text from images, identify warning labels, age restrictions, brand logos
- **Regulatory compliance**: Match findings against official regulatory requirements
- **Claims-Made-Seller**: Find all claims which falls under regulations and which needs to flagged against policy. For example, there might be claims like "cures cancer" which must be flagged and regulations for it must be verified.

🎯 Produce a clear step-by-step compliance analysis plan **as a valid Python list of strings** (no markdown, no explanations). 
Each step must be atomic, actionable, and assigned to one of the agents.
Maximum of {{steps_cap}} steps.
Each step must start with Agent Name followed by ":" i.e Agent Name: Task Assigned Statement.
Task Assigned statement must be atomic and actionable task with expected outcome statement specificied completely.

## Few Necessary Steps for Evaluation Process

### Initial Assessment
- Extract the specific marketplace where the product is intended to be sold.
- Identify the product category, key attributes, and any claims (Cures Cancer, Health benefits, FDA Approved) made by the product whcih requires supporting documentation.

### Consistency Check
Examine the product listing for any contradictory statements or claims that would require supporting documentation. Look for:
- Inconsistent product descriptions in different attributes of products, ex. age specificed > 14 yet kids shown in picture
- Unsubstantiated safety claims
- Conflicting information about materials, ingredients, or functionality

### Compliance Analysis
Evaluate the product against:
- Marketplace-specific regulations or regulatory bodies/website
- Product detail attributes like color, size, material which comes under regulations for the given marketplace
- Category-specific safety requirements
- Brand infringement concerns
- Recall policies
- Required certifications or documentation

These thought process mentioned as steps are not modular or atomic or independent enough to be solved by one research agent. These are just thought process. 
Use your discretion to understand what task must be given to an research agent such that it is atomic, actionable and can be completed by one research agent.

🚫 DO NOT include steps like "create CSV", "set up repo", "install packages".
✅ Focus on meaningful research tasks (search, extract, rank, draft, revise).
✅ Editor Agent must be called atleast once after the Writer Agent. 
✅ After Editor Agent, Research Agent/s must be triggered.
✅ Understand the overall task provided carefully and formulate a plan to research, write, revise.
✅ Understand the overall json output, few examples embedded in it, its objective and how you can plan to fill in each section of json in a correct and complete fashion.
✅ The FIRST step MUST be exactly: 
"Research agent: Use Tavily to perform a broad web search and find the main regulatory bodies or websites which defines regulation for the given marketplace and product category and charecteristics.

🔚 The FINAL step MUST instruct the writer agent to generate a comprehensive Markdown report with json output embedded in it such that:
- Uses all findings and outputs from previous steps
- Includes regulatory citations and policy URLs with clickable links/urls
- Includes a References section with clickable links for all citations
- Preserves earlier sources
- Is detailed and self-contained
- Produces Correct and Complete Json Output Required

Task: {{user_prompt}}

"""

    config = Config(read_timeout=1000)
    bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1', config=config)
    max_tokens = 100000
    budget_token = 80000
    
    # Create tool configuration
    # tool_config = create_tool_config()
    messages = [{"role": "user", "content": [{"text": user_prompt}]}]   
    response = bedrock_client.converse(
                    modelId=model_id,
                    system=[{"text": planner_agent_prompt}],
                    messages=messages,
                    inferenceConfig={"temperature": 1, "maxTokens": max_tokens},
                    additionalModelRequestFields={
                        "thinking": {
                            "type": "enabled",
                            "budget_tokens": budget_token
                        }
                    }
                )

    # Add response to conversation
    messages.append(response['output']['message'])
    
    # Check for tool use
    content_blocks = response['output']['message']['content']
    actual_planning_text = ''
    reasoning_text = ''
    for block in content_blocks:
        if 'reasoningContent' in block:
            reasoning_text += block['reasoningContent']['reasoningText']['text']
        elif 'text' in block:
            actual_planning_text += block['text']
    
    with open("output/current_planning_agent_reasoning.txt", "a+") as f:
        print(reasoning_text, file=f)

    with open("output/current_planning_agent_content_blocks.txt", "a+") as f:
        print(actual_planning_text, file=f)

    if not content_blocks:
        raise ValueError("No content blocks found in response")
    # --- robust parsing: JSON -> ast -> fallback ---
    def _coerce_to_list(s: str) -> List[str]:
        # try strict JSON
        try:
            obj = json.loads(s)
            if isinstance(obj, list) and all(isinstance(x, str) for x in obj):
                return obj[:7]
        except json.JSONDecodeError:
            pass
        # try Python literal list
        try:
            obj = ast.literal_eval(s)
            if isinstance(obj, list) and all(isinstance(x, str) for x in obj):
                return obj[:7]
        except Exception:
            pass
        # try to extract code fence if present
        if s.startswith("```") and s.endswith("```"):
            inner = s.strip("`")
            try:
                obj = ast.literal_eval(inner)
                if isinstance(obj, list) and all(isinstance(x, str) for x in obj):
                    return obj[:steps_cap + 1]
            except Exception:
                pass
        # Find Python code block containing the list
        code_block_pattern = r'```python\s*\n(.*?)\n```'
        match = re.search(code_block_pattern, s, re.DOTALL)
        
        if match:
            code_content = match.group(1).strip()
            try:
                # Parse the Python list
                steps_list = ast.literal_eval(code_content)
                return steps_list if isinstance(steps_list, list) else []
            except (ValueError, SyntaxError):
                pass
        
        # Fallback: extract lines that look like steps
        lines = s.split('\n')
        steps = []
        for line in lines:
            line = line.strip()
            if line.startswith('"') and 'agent:' in line and line.endswith('",'):
                steps.append(line.strip('",'))
        
        return steps   

    steps = _coerce_to_list(actual_planning_text)


    def _ensure_contract(steps_list: List[str]) -> List[str]:
        if not steps_list:
            raise ValueError("No steps provided")
        steps_list = [s for s in steps_list if isinstance(s, str)]
        if not steps_list or required_first[:50] not in steps_list[0]:
            steps_list = [required_first] + steps_list
        if len(steps_list) < 2 or required_second[:50] not in steps_list[1]:
            steps_list = (
                [steps_list[0]]
                + [required_second]
                + [
                    s
                    for s in steps_list[1:]
                ]
            )
        # ensure final step requirement present
        if required_final not in steps_list:
            steps_list.append(required_final)
        # cap to 7
        return steps_list[:steps_cap + 1]

    steps = _ensure_contract(steps)

    return steps

