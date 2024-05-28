# Copyright (c) 2024, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import requests
import torch
from typing import Dict, List, Optional
from rope import load_model

class HuggingFaceModel:
    def __init__(self, name_or_path: str, **generation_kwargs) -> None:
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

        self.tokenizer = AutoTokenizer.from_pretrained(name_or_path, trust_remote_code=True)
        if 'Yarn-Llama' in name_or_path:
            model_kwargs = None
        else:
            model_kwargs = {"attn_implementation": "flash_attention_2"}
        try:
            self.pipeline = pipeline(
                "text-generation",
                model=name_or_path,
                tokenizer=self.tokenizer,
                trust_remote_code=True,
                device_map="auto",
                torch_dtype=torch.bfloat16,
                model_kwargs=model_kwargs,
            )
            print("pipeline")
        except:
            print("not using pipeline")
            self.pipeline = None
            self.model = AutoModelForCausalLM.from_pretrained(name_or_path, trust_remote_code=True,torch_dtype=torch.bfloat16,)
            
        self.generation_kwargs = generation_kwargs
        self.stop = self.generation_kwargs.pop('stop')

    def __call__(self, prompt: str, **kwargs) -> Dict[str, List[str]]:
        if self.pipeline is None:
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            output = self.model.generate(
                **inputs,
                **self.generation_kwargs
            )
            generated_text = self.tokenizer.decode(output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        else:
            print(self.generation_kwargs)
            output = self.pipeline(text_inputs=prompt, **self.generation_kwargs,)
            assert len(output) == 1
            generated_text = output[0]["generated_text"]
        # print(generated_text)
        # remove the input form the generated text
        if generated_text.startswith(prompt):
            generated_text = generated_text[len(prompt) :]
                
        if self.stop is not None:
            for s in self.stop:
                generated_text = generated_text.split(s)[0]
        return {'text': [generated_text]}


class HuggingFaceModel_longrope:
    def __init__(self, name_or_path: str, **generation_kwargs) -> None:
        self.generation_kwargs = generation_kwargs
        print(self.generation_kwargs)
        # self.max_new_tokens = self.generation_kwargs.pop('max_new_tokens')
        from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline

        self.tokenizer = AutoTokenizer.from_pretrained(name_or_path, trust_remote_code=True)
        self.tokenizer.pad_token = self.tokenizer.eos_token
        rope_method = "longrope"
        rope_params = {
            'longrope_params_path': "/workspace/mnt/yuzhe/models/longrope_params/131072_swa131072_dm.csv",
            'longrope_scaling_policy': "su",
        }
        # dtype = 'auto' if args.dtype is None else getattr(torch, args.dtype)
        dtype = 'auto'
        model_kwargs = {"attn_implementation": "flash_attention_2"}
        print(self.generation_kwargs)
        self.max_position_embeddings = generation_kwargs.pop('max_position_embeddings')
        attn_implementation = "flash_attention_2"
        print(self.generation_kwargs)
        self.model = load_model(
            model_name_or_path=name_or_path,
            rope_method=rope_method,
            max_position_embeddings=self.max_position_embeddings,
            rope_params=rope_params,
            cache_dir="/mnt/logs/cache_dir",
            attn_implementation=attn_implementation,
            attn_sliding_window=131072,
            save_memory=False,
            torch_dtype=dtype,
            device_map='auto',
        )
        # try:
        self.pipeline = pipeline(
        task="text-generation",
        model=self.model,
        tokenizer=self.tokenizer,
        pad_token_id=self.tokenizer.eos_token_id,
        use_cache=True,
        device_map= "auto",
        model_kwargs=model_kwargs
    )
    #     print("pipeline")
        # self.pipeline = None
        # except:
        #     self.pipeline = None
        #     self.model = AutoModelForCausalLM.from_pretrained(name_or_path, trust_remote_code=True,torch_dtype=torch.bfloat16,).to("cuda")
            
        self.stop = self.generation_kwargs.pop('stop')

    def __call__(self, prompt: str, **kwargs) -> Dict[str, List[str]]:
        if self.pipeline is None:
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            output = self.model.generate(
                **inputs,
                **self.generation_kwargs,
                use_cache=False
            )
            generated_text = self.tokenizer.decode(output[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        else:
            self.generation_kwargs["max_new_tokens"] = 50
            response = self.pipeline(prompt, **self.generation_kwargs)
            generated_text = response[0]["generated_text"]
            
        # remove the input form the generated text
        if generated_text.startswith(prompt):
            generated_text = generated_text[len(prompt) :]
                
        if self.stop is not None:
            for s in self.stop:
                generated_text = generated_text.split(s)[0]
        return {'text': [generated_text]}
class MambaModel:
    def __init__(self, name_or_path: str, **generation_kwargs) -> None:
        from transformers import AutoTokenizer
        from mamba_ssm.models.mixer_seq_simple import MambaLMHeadModel

        self.tokenizer = AutoTokenizer.from_pretrained("EleutherAI/gpt-neox-20b")
        self.device = "cuda"
        self.model = MambaLMHeadModel.from_pretrained(name_or_path, device=self.device, dtype=torch.bfloat16)
        self.generation_kwargs = generation_kwargs
        self.stop = self.generation_kwargs.pop('stop')
        self.max_genlen = self.generation_kwargs.pop('max_new_tokens')
        self.minp = 0.0

    def __call__(self, prompt: str, **kwargs) -> Dict[str, List[str]]:
        # tokenize
        tokens = self.tokenizer(prompt, return_tensors="pt")
        input_ids = tokens.input_ids.to(self.device)
        max_length = input_ids.shape[1] + self.max_genlen

        # generate
        out = self.model.generate(
            input_ids=input_ids,
            max_length=max_length,
            cg=True,
            return_dict_in_generate=True,
            output_scores=True,
            enable_timing=False,
            **self.generation_kwargs,
        )
        assert len(out.sequences) == 1
        # detok
        return {'text': [self.tokenizer.decode(out.sequences[0][input_ids.shape[1] :])]}