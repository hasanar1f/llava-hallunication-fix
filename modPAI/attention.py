import math
import types
from typing import Optional, Tuple
import pickle
import torch
import torch.nn as nn
from transformers.models.llama.modeling_llama import apply_rotary_pos_emb
import os
import matplotlib.pyplot as plt
import torch

def analyze_attention_weights(attn_weights, layer_idx, save_dir="attn_analysis"):
    """
    Analyze and visualize attention weights.
    
    Parameters:
        attn_weights (torch.Tensor): The attention weight tensor of shape (batch_size, num_heads, q_len, kv_len).
        layer_idx (int): The current layer index for labeling.
        save_dir (str): Directory to save the analysis plots.
    """
    if not isinstance(attn_weights, torch.Tensor):
        pass
    
    attn_weights = attn_weights.detach().cpu()
    
    mean = attn_weights.mean().item()
    std = attn_weights.std().item()
    max_val = attn_weights.max().item()
    min_val = attn_weights.min().item()
    
    
    batch_idx = 0  # Example: visualize the first sample in the batch
    head_idx = 0   # Example: visualize the first attention head
    
    attn_matrix = attn_weights[batch_idx, head_idx]  # Shape: (q_len, kv_len)
    
    plt.figure(figsize=(10, 6))
    plt.imshow(attn_matrix, cmap='viridis', aspect='auto')
    plt.xlabel("Attention Score")
    plt.ylabel("Token index")
    plt.title(f"Layer {layer_idx} - Attention Distribution (Head {head_idx})")
    
    # Save the plot
    os.makedirs(save_dir, exist_ok=True)
    save_path = f"{save_dir}/attn_layer_{layer_idx}_head_{head_idx}.png"
    plt.savefig(save_path)
    plt.close()
    
    print(f"Attention visualization saved to {save_path}")


def llama_new_forward(
    self,
    hidden_states: torch.Tensor,
    attention_mask: Optional[torch.Tensor] = None,
    position_ids: Optional[torch.LongTensor] = None,
    past_key_value: Optional[Tuple[torch.Tensor]] = None,
    output_attentions: bool = False,
    use_cache: bool = False,
) -> Tuple[torch.Tensor, Optional[torch.Tensor], Optional[Tuple[torch.Tensor]]]:
    bsz, q_len, _ = hidden_states.size()

    query_states = (
        self.q_proj(hidden_states)
        .view(bsz, q_len, self.num_heads, self.head_dim)
        .transpose(1, 2)
    )
    key_states = (
        self.k_proj(hidden_states)
        .view(bsz, q_len, self.num_heads, self.head_dim)
        .transpose(1, 2)
    )
    value_states = (
        self.v_proj(hidden_states)
        .view(bsz, q_len, self.num_heads, self.head_dim)
        .transpose(1, 2)
    )

    kv_seq_len = key_states.shape[-2]
    if past_key_value is not None:
        if self.layer_idx is None:
            raise ValueError(
                f"The cache structure has changed since version v4.36. If you are using {self.__class__.__name__} "
                "for auto-regressive decoding with k/v caching, please make sure to initialize the attention class "
                "with a layer index."
            )
        kv_seq_len += past_key_value.get_usable_length(kv_seq_len, self.layer_idx)
    cos, sin = self.rotary_emb(value_states, seq_len=kv_seq_len)
    query_states, key_states = apply_rotary_pos_emb(
        query_states, key_states, cos, sin, position_ids
    )

    if past_key_value is not None:
        cache_kwargs = {"sin": sin, "cos": cos}  # Specific to RoPE models
        key_states, value_states = past_key_value.update(
            key_states, value_states, self.layer_idx, cache_kwargs
        )

    attn_weights = torch.matmul(query_states, key_states.transpose(2, 3)) / math.sqrt(
        self.head_dim
    )

    if attn_weights.size() != (bsz, self.num_heads, q_len, kv_seq_len):
        raise ValueError(
            f"Attention weights should be of size {(bsz, self.num_heads, q_len, kv_seq_len)}, but is"
            f" {attn_weights.size()}"
        )

    if attention_mask is not None:
        if attention_mask.size() != (bsz, 1, q_len, kv_seq_len):
            raise ValueError(
                f"Attention mask should be of size {(bsz, 1, q_len, kv_seq_len)}, but is {attention_mask.size()}"
            )
        attn_weights = attn_weights + attention_mask
        attn_weights = torch.max(
            attn_weights, torch.tensor(torch.finfo(attn_weights.dtype).min)
        )

    ### PAI's modification
    if hasattr(self, "use_attn"):
        use_attn = self.use_attn
        img_start_idx = self.img_start_idx
        img_end_idx = self.img_end_idx
    else:
        use_attn = False

    if hasattr(self, "use_cfg"):
        use_cfg = self.use_cfg
    else:
        use_cfg = False

    modpai = True # True or False
    
    if modpai: ### MODPAI # todo: ablation
        top_tokens = self.shared_dict['top_tokens'] + self.img_start_idx # offset by img_start_idx
        bottom_tokens = self.shared_dict['bottom_tokens'] + self.img_start_idx
        # self.alpha = 0.7
        # self.beta = 0.3
        if use_attn and not use_cfg:
            attn_weights[:, :, -1, top_tokens ] = (
                attn_weights[:, :, -1, top_tokens].abs() * self.alpha
                + attn_weights[:, :, -1, top_tokens]
            )  
            attn_weights[:, :, -1, bottom_tokens ] = (
                attn_weights[:, :, -1, bottom_tokens].abs() * self.beta
                + attn_weights[:, :, -1, bottom_tokens]
            )
        # if isinstance(attn_weights, torch.Tensor) and self.use_cfg == False and self.layer_idx == 15 and attn_weights.shape[-1] == 699:
        #     analyze_attention_weights(attn_weights, self.layer_idx, save_dir="modpai")
    else: # PAI original
        if use_attn and not use_cfg:
            attn_weights[:, :, -1, img_start_idx:img_end_idx] = (
                attn_weights[:, :, -1, img_start_idx:img_end_idx].abs() * self.alpha
                + attn_weights[:, :, -1, img_start_idx:img_end_idx]
            )  
        # if isinstance(attn_weights, torch.Tensor) and self.use_cfg == False and self.layer_idx == 15 and attn_weights.shape[-1] == 699:
        #     analyze_attention_weights(attn_weights, self.layer_idx, save_dir="pai")



    attn_weights = nn.functional.softmax(attn_weights, dim=-1, dtype=torch.float32).to(
        query_states.dtype
    )

    attn_output = torch.matmul(attn_weights, value_states)

    if attn_output.size() != (bsz, self.num_heads, q_len, self.head_dim):
        raise ValueError(
            f"`attn_output` should be of size {(bsz, self.num_heads, q_len, self.head_dim)}, but is"
            f" {attn_output.size()}"
        )

    attn_output = attn_output.transpose(1, 2)
    attn_output = attn_output.reshape(bsz, q_len, self.hidden_size)

    attn_output = self.o_proj(attn_output)

    if not output_attentions:
        attn_weights = None

    return attn_output, attn_weights, past_key_value


def llama_modify(model, start_layer, end_layer, use_attn, alpha, beta, use_cfg,
                 img_start_idx, img_end_idx):
    # print("<<< modifying the attention in the llava forward pass >>>")
    shared_dict = {'vit_attn': None}
    model.model.vision_tower.shared_dict = shared_dict
    for i in range(start_layer, end_layer):
        model.model.layers[i].self_attn.shared_dict = shared_dict
        model.model.layers[i].self_attn.use_attn = use_attn
        model.model.layers[i].self_attn.alpha = alpha
        model.model.layers[i].self_attn.beta = beta
        model.model.layers[i].self_attn.use_cfg = use_cfg
        model.model.layers[i].self_attn.img_start_idx = img_start_idx
        model.model.layers[i].self_attn.img_end_idx = img_end_idx
        model.model.layers[i].self_attn.forward = types.MethodType(llama_new_forward, model.model.layers[i].self_attn)
