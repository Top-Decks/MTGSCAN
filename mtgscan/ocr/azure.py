import logging
import os
import time
import re
import base64

import requests
from mtgscan.box_text import BoxTextList
from mtgscan.utils import is_url
from .ocr import OCR


class Azure(OCR):

    def __init__(self):
        try:
            self.subscription_key = os.environ['AZURE_VISION_KEY']
            self.text_recognition_url = os.environ['AZURE_VISION_ENDPOINT'] + \
                "/vision/v3.2/read/analyze"
        except IndexError as e:
            print(str(e))
            print(
                "Azure credentials should be stored in environment variables AZURE_VISION_KEY and AZURE_VISION_ENDPOINT"
            )

    def __str__(self):
        return "Azure"

    def _is_base64_string(self, s: str) -> bool:
        """检测字符串是否为base64编码的图片数据
        
        Args:
            s: 待检测的字符串
            
        Returns:
            bool: 如果是base64编码返回True，否则返回False
        """
        if not isinstance(s, str) or len(s) < 20:
            return False
            
        # 检查是否包含base64字符集
        base64_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
        if not all(c in base64_chars for c in s):
            return False
            
        # 检查长度是否为4的倍数（base64特征）
        if len(s) % 4 != 0:
            return False
            
        # 检查是否以常见图片格式的base64开头
        image_prefixes = [
            '/9j/',  # JPEG
            'iVBORw0KGgo',  # PNG
            'R0lGOD',  # GIF
            'UklGR'   # WebP (RIFF)
        ]
        
        if any(s.startswith(prefix) for prefix in image_prefixes):
            return True
            
        # 尝试解码来验证是否为有效的base64
        try:
            decoded = base64.b64decode(s, validate=True)
            # 检查解码后的数据是否以图片文件头开始
            if len(decoded) >= 4:
                # JPEG: FF D8 FF
                if decoded[:3] == b'\xff\xd8\xff':
                    return True
                # PNG: 89 50 4E 47
                if decoded[:4] == b'\x89PNG':
                    return True
                # GIF: 47 49 46 38
                if decoded[:4] in [b'GIF8', b'GIF9']:
                    return True
                # WebP: 52 49 46 46
                if decoded[:4] == b'RIFF' and len(decoded) >= 12 and decoded[8:12] == b'WEBP':
                    return True
            return False
        except Exception:
            return False
    
    def _safe_log_image_info(self, image: str, image_type: str) -> None:
        """安全地记录图片信息，避免打印完整的base64字符串
        
        Args:
            image: 图片数据或路径
            image_type: 图片类型描述
        """
        if image_type == "base64":
            # 只显示base64字符串的前20个字符
            preview = image[:20] + "..." if len(image) > 20 else image
            logging.info(f"Reading image as base64 (length: {len(image)}, preview: {preview})")
        else:
            logging.info(f"Reading image from {image_type}: {image}")

    def image_to_box_texts(self, image: str, is_base64=False) -> BoxTextList:
        """将图片转换为文本框列表
        
        Args:
            image: 图片URL、文件路径或base64编码字符串
            is_base64: 是否为base64编码（可选，会自动检测）
            
        Returns:
            BoxTextList: 识别出的文本框列表
        """
        headers = {'Ocp-Apim-Subscription-Key': self.subscription_key}
        json, data = None, None
        
        if is_url(image):
            self._safe_log_image_info(image, "URL")
            json = {'url': image}
        else:
            headers['Content-Type'] = 'application/octet-stream'
            
            # 自动检测base64或使用显式参数
            detected_base64 = is_base64 or self._is_base64_string(image)
            
            if detected_base64:
                self._safe_log_image_info(image, "base64")
                try:
                    data = base64.b64decode(image)
                except Exception as e:
                    raise Exception(f"Failed to decode base64 image data: {str(e)}")
            else:
                # 检查文件是否存在，避免将base64字符串当作文件路径
                if not os.path.isfile(image):
                    # 如果不是文件且看起来像base64，尝试作为base64处理
                    if len(image) > 100 and not os.path.sep in image:
                        logging.warning(f"Image parameter looks like base64 but detection failed, attempting base64 decode")
                        try:
                            data = base64.b64decode(image)
                            self._safe_log_image_info(image, "base64")
                        except Exception:
                            raise FileNotFoundError(f"File not found and base64 decode failed: {image[:50]}...")
                    else:
                        raise FileNotFoundError(f"Image file not found: {image}")
                else:
                    self._safe_log_image_info(image, "file")
                    try:
                        with open(image, "rb") as f:
                            data = f.read()
                    except Exception as e:
                        raise Exception(f"Failed to read image file {image}: {str(e)}")
        logging.info(f"Sending image to Azure")
        try:
            response = requests.post(
                self.text_recognition_url, headers=headers, json=json, data=data, timeout=30)
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to send request to Azure API: {str(e)}")
            
        # 检查初始响应状态
        if response.status_code != 202:
            try:
                error_info = response.json()
                error_message = error_info.get("error", {}).get("message", "Unknown error")
                error_code = error_info.get("error", {}).get("code", "Unknown code")
                raise Exception(f"Azure API request failed (HTTP {response.status_code}): {error_code} - {error_message}")
            except ValueError:
                raise Exception(f"Azure API request failed (HTTP {response.status_code}): {response.text}")
        
        # 检查是否有Operation-Location头
        if "Operation-Location" not in response.headers:
            raise Exception("Azure API response missing Operation-Location header")
            
        # 轮询结果
        operation_url = response.headers["Operation-Location"]
        logging.info(f"Polling Azure operation: {operation_url}")
        
        max_polls = 60  # 最多轮询60次（60秒）
        poll_count = 0
        
        while poll_count < max_polls:
            try:
                response_final = requests.get(operation_url, headers=headers, timeout=10)
                if response_final.status_code != 200:
                    raise Exception(f"Failed to poll Azure operation (HTTP {response_final.status_code})")
                    
                analysis = response_final.json()
            except requests.exceptions.RequestException as e:
                raise Exception(f"Failed to poll Azure operation: {str(e)}")
            except ValueError as e:
                raise Exception(f"Invalid JSON response from Azure: {str(e)}")
            
            status = analysis.get('status', 'unknown')
            logging.debug(f"Azure operation status: {status}")
            
            if status == 'succeeded' and "analyzeResult" in analysis:
                break
            elif status == 'failed':
                error_msg = analysis.get('error', {}).get('message', 'Operation failed')
                raise Exception(f"Azure OCR operation failed: {error_msg}")
            elif status in ['running', 'notStarted']:
                time.sleep(1)
                poll_count += 1
            else:
                raise Exception(f"Unknown Azure operation status: {status}")
        
        if poll_count >= max_polls:
            raise Exception("Azure OCR operation timed out after 60 seconds")
            
        # 解析结果
        try:
            read_results = analysis["analyzeResult"]["readResults"]
            if not read_results:
                logging.warning("No text detected in image")
                return BoxTextList()
                
            box_texts = BoxTextList()
            for page in read_results:
                for line in page.get("lines", []):
                    if "boundingBox" in line and "text" in line:
                        box_texts.add(line["boundingBox"], line["text"])
            
            logging.info(f"Successfully extracted {len(box_texts.box_texts)} text lines")
            return box_texts
            
        except (KeyError, IndexError) as e:
            raise Exception(f"Unexpected Azure API response format: {str(e)}")
