import io
import boto3 
import json 
import os 
import re
from dotenv import load_dotenv


load_dotenv()


class ns:
    def __init__(self, filename):
        self.aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        self.region = os.getenv("REGION")
        self.model_ID = os.getenv("MODEL_ID")
        self.filename = "notebooklogs/notebook_experiments/" + self.find_file_match(filename)

        print(f'Running AWS Bedrock: {self.model_ID}')

        self.accept = 'application/json'
        self.contentType = 'application/json'
        
    def find_file_match(self, filename):
        registered_files = os.listdir("notebooklogs/notebook_experiments")
        
        base_name = os.path.splitext(os.path.basename(filename))[0]
        
        
        match = next((f for f in registered_files if re.match(rf"^{re.escape(base_name)}(_io)?\.log$", f)), None)
        return match 


    def read_file(self):
        print(self.filename)
        with open(self.filename, 'r', encoding = 'utf-8') as file:
            text_content = file.read()
        return text_content

    def create_prompt(self,main_content):
        instructions = """You are an expert software engineer and data scientist tasked with summarizing the activity and progress in a code notebook based on detailed execution logs.
        Your goal is to produce a clear, concise, and structured report that helps the team understand:
        - What functions or classes were defined and their purpose
        - Which code cells were actually run, and what key results or outputs were produced
        - Any loops or data processing pipelines executed and their significance
        - Any machine learning models built or prepared, and their current status (defined, trained, used)
        - Suggestions or notes on what might be missing or next logical steps
        the summary should be easy to understand for technical stakeholders familiar with Python and data science but may not have seen this code before.
        Format your output as a readable report with paragraphs and bullet points where appropriate.
        Below are the detailed logs and code snippets from the notebook execution:
        """

        final = """Please generate the summary report now."""

        llm_prompt2 = f"""
        You are an expert software engineer and data scientist tasked with summarizing the activity and progress in a code notebook based on detailed execution logs.
        Your goal is to produce a clear, detailed, and structured report that helps the team understand:
        - Which code cells were actually run, and what key results or outputs were produced
        ## Logs:
        {main_content}
        Please generate the summary report now.    
        """

        llm_prompt = instructions + main_content + final

        return llm_prompt2

    def get_llm_response(self,llm_prompt):
        brt = boto3.client('bedrock-runtime', region_name = self.region,
                       aws_access_key_id=self.aws_access_key_id,
                       aws_secret_access_key=self.aws_secret_access_key)
        body = json.dumps({
        'prompt':llm_prompt,
        })
        response = brt.invoke_model(body = body, modelId = self.model_ID)
        response_body = json.loads(response.get('body').read())
        return response_body

    def save_file(self,response_body):
        generation_text = response_body.get('generation', '')
        with open('summary_report.txt', 'w', encoding='utf-8')as f:
            f.write(generation_text)

    def driver(self):
        mc = self.read_file()
        llm_prompt_final = self.create_prompt(mc)
        llm_response = self.get_llm_response(llm_prompt_final)
        print(llm_response["generation"])
        return llm_response["generation"]


    if __name__=='__main__':

        mc = read_file()
        llm_prompt_final = create_prompt(mc)
        llm_response = get_llm_response(llm_prompt_final)
        save_file(llm_response)
        print(llm_response)

