import pandas as pd
from nodetools.ai.openai import OpenAIRequestTool
from nodetools.prompts import task_generation
from nodetools.utilities.settings import NODE_NAME
from nodetools.utilities.settings import NODE_ADDRESS
from nodetools.prompts.initiation_rite import phase_4__system
from nodetools.prompts.initiation_rite import phase_4__user
from nodetools.ai.openai import OpenAIRequestTool
from nodetools.prompts.task_generation import phase_1_b__user
from nodetools.prompts.task_generation import phase_1_b__system
from nodetools.prompts.task_generation import phase_1_b__user
from nodetools.prompts.task_generation import phase_1_b__system
import xrpl
from xrpl.clients import JsonRpcClient
from xrpl.models.requests import AccountInfo, AccountLines
#password_map_loader = PasswordMapLoader()
import numpy as np
from xrpl.wallet import Wallet
from xrpl.clients import JsonRpcClient
from xrpl.core.keypairs import derive_classic_address
from nodetools.utilities.generic_pft_utilities import *
from nodetools.prompts.rewards_manager import verification_user_prompt
from nodetools.prompts.rewards_manager import verification_system_prompt
from nodetools.prompts.rewards_manager import reward_system_prompt
from nodetools.prompts.rewards_manager import reward_user_prompt
from nodetools.utilities.db_manager import DBConnectionManager

class PostFiatTaskGenerationSystem:
    def __init__(self,pw_map):
        self.pw_map = pw_map
        self.default_model = 'chatgpt-4o-latest'
        self.openai_request_tool= OpenAIRequestTool(pw_map=self.pw_map)
        self.generic_pft_utilities = GenericPFTUtilities(pw_map=self.pw_map, node_name=NODE_NAME)
        self.node_address = NODE_ADDRESS
        self.node_seed = self.pw_map['postfiatfoundation__v1xrpsecret']
        self.node_wallet = self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=self.node_seed)
        self.stop_threads = False
        self.db_connection_manager = DBConnectionManager(pw_map=pw_map)

    def output_initiation_rite_df(self, all_node_memo_transactions):
        """
        all_node_transactions = self.generic_pft_utilities.get_all_cached_transactions_related_to_account(self.node_address).copy()
        all_node_memo_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=self.node_address, pft_only=False).copy()
        """
        initiation_rewards = all_node_memo_transactions[all_node_memo_transactions['memo_type']=='INITIATION_REWARD'][['user_account',
                                                                                                  'memo_data','memo_format',
                                                                                                  'directional_pft']].groupby('user_account').last()[['memo_data',
                                                                                                                                                      'directional_pft',
                                                                                                                                                      'memo_format']]
        rites = all_node_memo_transactions[all_node_memo_transactions['memo_type']=="INITIATION_RITE"][['user_account',
                                                                                                'memo_data']].groupby('user_account').last()
        rites.columns=['initiation_rite']
        initiation_rite_cue_df = pd.concat([rites, initiation_rewards],axis=1).reset_index()
        initiation_rite_cue_df['requires_work']= np.where((initiation_rite_cue_df['initiation_rite'].apply(lambda x: len(str(x)))>10)
                 & (initiation_rite_cue_df['memo_data'].apply(lambda x: 'INITIATION_REWARD' not in str(x))),1,0)
        return initiation_rite_cue_df

    def phase_1_construct_required_post_fiat_generation_cue(self, all_account_info):
        """ This is where the dataframe of requested tasks come from 
        Google Docs are appended to the dataframe as well. Operates
        on most recent tasks only 
        
        account_to_study = self.user_wallet.classic_address
        #account_to_study
        all_account_info =self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=account_to_study,
                    transaction_limit=5000)
        """ 

        simplified_task_frame = self.generic_pft_utilities.convert_all_account_info_into_simplified_task_frame(all_account_info=
                                                                all_account_info)
        most_recent_tasks = simplified_task_frame.sort_values('datetime').copy().groupby('task_id').last()
        required_post_fiat_generation_cue = most_recent_tasks[most_recent_tasks['full_output'].apply(lambda x: 
                                                                'REQUEST_POST_FIAT ___' in x)]
        required_post_fiat_generation_cue['google_doc']=None
        if len(required_post_fiat_generation_cue)>0:
            print('moo')
            required_post_fiat_generation_cue['google_doc']= required_post_fiat_generation_cue.apply(lambda x: self.get_most_recent_google_doc_for_user(user_account=x['user_account'],
                                                                                                    all_account_info=all_account_info),axis=1)
        return required_post_fiat_generation_cue 
    
    def phase_1_a__initial_task_generation_api_args(self,full_user_context_replace,
                                                    user_request='I want something related to the Post Fiat Network'):
        """ EXAMPLE ACCOUNT ADDRESS
        r3UHe45BzAVB3ENd21X9LeQngr4ofRJo5n
        full_user_context_replace = self.generic_pft_utilities.get_full_user_context_string(account_address=account_address)
        """ 
        #full_user_context_replace = self.generic_pft_utilities.get_full_user_context_string(account_address=account_address)
        context_augment  = f'''<THE USER SPECIFIC TASK REQUEST STARTS HERE>
        {user_request}
        <THE USER SPECIFIC TASK REQUEST ENDS HERE>'''
        full_augmented_context=full_user_context_replace+context_augment
        api_args = {
            "model": self.default_model,
            "messages": [
                {"role": "system", "content": task_generation.phase_1_a__system},
                {"role": "user", "content": task_generation.phase_1_a__user.replace('___FULL_USER_CONTEXT_REPLACE___',full_augmented_context)}
            ]}
        return api_args

    def create_multiple_copies_of_df(self, df, n_copies):
        """
        Create multiple copies of a dataframe and add a unique index column.
        Args:
        df (pd.DataFrame): Input dataframe
        n_copies (int): Number of copies to create
        Returns:
        pd.DataFrame: Concatenated dataframe with unique index column
        """
        copies = [df.copy() for _ in range(n_copies)]
        result = pd.concat(copies, ignore_index=True)
        result['unique_index'] = range(len(result))
        return result

    def phase_1_a__n_post_fiat_task_generator(self, full_user_context_replace, user_request, n_copies):
        """
        EXAMPLE
        account_address = 'r3UHe45BzAVB3ENd21X9LeQngr4ofRJo5n'
        user_request='I want something related to the Post Fiat Network'
        n_copies = 3
        """
        n_copies = n_copies 
        user_api_arg = self.phase_1_a__initial_task_generation_api_args(full_user_context_replace=full_user_context_replace,
                                                                       user_request=user_request)
        copy_frame = pd.DataFrame([[user_api_arg]])
        copy_frame.columns=['api_args']
        full_copy_df = self.create_multiple_copies_of_df(df=copy_frame, n_copies= n_copies)
        async_dict_to_work = full_copy_df.set_index('unique_index')['api_args'].to_dict()
        output = self.openai_request_tool.create_writable_df_for_async_chat_completion(arg_async_map=async_dict_to_work)
        result_map = output[['internal_name','choices__message__content']].groupby('internal_name').first()['choices__message__content']
        full_copy_df['output']=full_copy_df['unique_index'].map(result_map)
        full_copy_df['task_string']=full_copy_df['output'].apply(lambda x: x.split('Final Output |')[-1:][0].split('|')[0].strip())
        full_copy_df['value']=full_copy_df['output'].apply(lambda x: x.split('| Value of Task |')[-1:][0].replace('|','').strip())
        full_copy_df['classification']='OUTPUT '+(full_copy_df['unique_index']+1).astype(str)
        full_copy_df['simplified_string']= full_copy_df['task_string']+' .. '+full_copy_df['value']
        output_string = '\n'.join(list(full_copy_df['simplified_string']))
        return {'full_api_output': full_copy_df, 'n_task_output': output_string}
        
    def convert_all_node_memo_transactions_to_required_pft_generation(self, all_node_memo_transactions):
        """
        all_node_memo_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=self.node_address, pft_only=False).copy()
        """
        most_recent_memo = all_node_memo_transactions.sort_values('datetime').groupby('memo_type').last()['memo_data']
        postfiat_request_cue = all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: 
                                                                                 'REQUEST_POST_FIAT' in x)].sort_values('datetime')
        postfiat_request_cue['most_recent_status']=postfiat_request_cue['memo_type'].map(most_recent_memo)
        postfiat_request_cue['requires_work']=postfiat_request_cue['most_recent_status'].apply(lambda x: 'REQUEST_POST_FIAT' in x)
        return postfiat_request_cue

    def discover_server__initiation_rite(self, account_seed, initiation_rite, google_doc_link, username):
        """ EXAMPLE:
            account_seed = 'sEdSqchDCHj29NoRhcsZ8EQfbAkbBJ2'
            initation_rite = "I commit to generating massive profits trading by 2026"
            google_doc_link='https://docs.google.com/document/d/1M7EW9ocKDnbnSZ1Xa5FanfhRbteVJYV-iNOsvj5bGf4/edit'
            username = 'funkywallet'
        """ 
        error_string = '' 
        foundation_wallet = self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=self.node_seed)
        wallet = self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=account_seed)
        account_address = wallet.classic_address
        all_holders = list(self.generic_pft_utilities.output_post_fiat_holder_df()['account'].unique())
        # step 1 -- verify that the wallet has a trust line and if it does not establish it 
        if account_address in all_holders:
            print('already is PFT holder')
        if account_address not in all_holders:
            self.generic_pft_utilities.generate_trust_line_to_pft_token(wallet_seed=account_seed)
            memo = self.generic_pft_utilities.construct_basic_postfiat_memo(user='postfiatfoundation',
                                                      task_id='discord_wallet_funding',
                                                      full_output='Initial PFT Grant Pre Initiation')
            self.generic_pft_utilities.send_PFT_with_info(sending_wallet=foundation_wallet, amount=10, memo=memo, destination_address=wallet.classic_address)
        error_string = ''
        all_account_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=self.node_address, pft_only=False)
        all_google_docs = all_account_transactions[all_account_transactions['memo_type'].apply(lambda x: 'google_doc_context_link' in x) 
        & (all_account_transactions['user_account'] == account_address)][['memo_type','memo_data','memo_format','user_account']]
        
        google_doc = ''
        if len(all_google_docs)>0:
            google_doc_row = all_google_docs.tail(1)
            google_doc = list(google_doc_row['memo_data'])[0]
            print(f'Already has a google doc: {google_doc}')
        
        if google_doc == '':
            print('sending google doc')
            balance = self.generic_pft_utilities.check_if_there_is_funded_account_at_front_of_google_doc(google_url=google_doc_link)
            print(f'XRPL balance is {balance}')
            if balance <=12:
                error_string = error_string+'Insufficient XRP Balance'
            if balance>12:
                google_memo = self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=google_doc_link, 
                                                                                          memo_format=username, 
                                                                                          memo_type='google_doc_context_link')
                self.generic_pft_utilities.send_PFT_with_info(sending_wallet=wallet, 
                                                              amount=1, 
                                                              destination_address=self.node_address, 
                                                              memo=google_memo)
        
            #memo_to_send = self.generate_initiation_rite_context_memo(user=user, user_response=user_response)
            balance = self.generic_pft_utilities.check_if_there_is_funded_account_at_front_of_google_doc(google_url=google_doc_link)
            if balance>12:
                initiation_memo_to_send = self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data= initiation_rite, memo_format = username, memo_type='INITIATION_RITE')
            number_of_initiation_rites = len(all_account_transactions[(all_account_transactions['memo_type']=='INITIATION_RITE') & (all_account_transactions['user_account']==account_address)])
            print("NUmber of initiation rites", number_of_initiation_rites)
            if number_of_initiation_rites ==0:
                xo = self.generic_pft_utilities.send_xrp_with_info__seed_based(wallet_seed=account_seed, amount=1, destination=self.node_address, memo=initiation_memo_to_send)
                print("INITIATION RITE SENT")
            #self.generate_trust_line_to_pft_token(wallet_seed=wallet_seed)
            if number_of_initiation_rites >0:
                error_string = error_string+"initiation rite already sent for this account"
        if google_doc!='':
            balance = self.generic_pft_utilities.check_if_there_is_funded_account_at_front_of_google_doc(google_url=google_doc_link)
            if balance>12:
                initiation_memo_to_send = self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data= initiation_rite, memo_format = username, memo_type='INITIATION_RITE')
            number_of_initiation_rites = len(all_account_transactions[(all_account_transactions['memo_type']=='INITIATION_RITE') & (all_account_transactions['user_account']==account_address)])
            print("NUmber of initiation rites", number_of_initiation_rites)
            if number_of_initiation_rites ==0:
                xo = self.generic_pft_utilities.send_xrp_with_info__seed_based(wallet_seed=account_seed, amount=1, destination=self.node_address, memo=initiation_memo_to_send)
                print("INITIATION RITE SENT")
                error_string = self.generic_pft_utilities.extract_transaction_info_from_response_object(xo)['clean_string']
            #self.generate_trust_line_to_pft_token(wallet_seed=wallet_seed)
            if number_of_initiation_rites >0:
                error_string = error_string+"initiation rite already sent for this account"
        return error_string
    
    def node_cue_function__initiation_rewards(self):
        all_account_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=self.node_address, pft_only=False)
        rite_cue  = self.output_initiation_rite_df(all_node_memo_transactions=all_account_transactions)
        rite_cue_to_work = rite_cue[rite_cue['requires_work']==1].copy()
        if len(rite_cue_to_work)>0:
            def create_initiation_rite_api_args(initiation_rite_text):
                api_args = {
                            "model": self.default_model,
                            "messages": [
                                {"role": "system", "content": phase_4__system},
                                {"role": "user", "content": phase_4__user.replace('___USER_INITIATION_RITE___',initiation_rite_text)}
                            ]
                        }
                return api_args
            rite_cue_to_work['api_args']=rite_cue_to_work['initiation_rite'].apply(lambda x: create_initiation_rite_api_args(x))
            def extract_reward_from_async_response(xstr):
                ret = 10
                try:
                    ret = int(xstr.split('| Reward |')[-1:][0].replace('|','').strip())
                except:
                    pass
                return ret
            
            def extract_justification_from_async_response(xstr):
                justification = 'unparseable but some reward allocated'
                try:
                    justification = xstr.split(' Justification |')[-1:][0].split('|')[0].strip()
                except:
                    pass
                return justification
            async_response = self.openai_request_tool.create_writable_df_for_async_chat_completion(arg_async_map=rite_cue_to_work.set_index('user_account')['api_args'].to_dict())
            async_response['reward']=async_response['choices__message__content'].apply(lambda x: extract_reward_from_async_response(x))
            async_response['justification']= async_response['choices__message__content'].apply(lambda x: extract_justification_from_async_response(x))[0]
            async_response['full_output_message'] = "INITIATION_REWARD ___ "+async_response['justification']
            async_response['memo_to_send']= async_response['full_output_message'].apply(lambda x: self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=x, 
                                                                        memo_type="INITIATION_REWARD", memo_format="postfiatfoundation"))
            async_response.apply(lambda x: self.generic_pft_utilities.send_PFT_with_info(sending_wallet= self.node_wallet,amount=x['reward'],
                                                                                     memo=x['memo_to_send'], destination_address=x['internal_name']),axis=1)

    def discord__send_postfiat_request(self, user_request, user_name, seed):
        """
        user_request = 'I want a task'
        user_name = '.goodalexander'
        seed = 's____S'
        """ 
        task_id = self.generic_pft_utilities.generate_custom_id()
        full_memo_string = 'REQUEST_POST_FIAT ___ '+user_request
        memo_type= task_id
        memo_format = user_name
        xmemo_to_send = self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=full_memo_string, 
                                                                    memo_type=memo_type,
                                                                    memo_format=memo_format)
        sending_wallet = self.generic_pft_utilities.spawn_user_wallet_from_seed(seed)
        op_response = self.generic_pft_utilities.send_PFT_with_info(sending_wallet=sending_wallet,
            amount=1,
            memo=xmemo_to_send,
            destination_address=self.generic_pft_utilities.node_address,
            url=None)
        return op_response 

    def discord__task_acceptance(self,seed_to_work,user_name, task_id_to_accept,acceptance_string):
        """ EXAMPLE PARAMS
        seed_to_work = 's___'
        user_name = '.goodalexander'
        task_id_to_accept = '2024-08-17_17:57__TO94'
        acceptance_string = "I will get this done as soon as I am able" 
        """
        wallet= self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=seed_to_work)
        wallet_address = wallet.classic_address
        all_wallet_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(wallet_address).copy()
        pf_df = self.generic_pft_utilities.convert_all_account_info_into_outstanding_task_df(account_memo_detail_df=all_wallet_transactions)
        valid_task_ids_to_accept= list(pf_df[pf_df['acceptance']==''].index)
        if task_id_to_accept in valid_task_ids_to_accept:
            print('valid task ID proceeding to accept')
            formatted_acceptance_string = 'ACCEPTANCE REASON ___ '+acceptance_string
            acceptance_memo= self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=formatted_acceptance_string, 
                                                                                        memo_format=user_name, memo_type=task_id_to_accept)
            acceptance_response = self.generic_pft_utilities.send_PFT_with_info(sending_wallet=wallet, amount=1, memo=acceptance_memo, destination_address=self.node_address)
            transaction_info = self.generic_pft_utilities.extract_transaction_info_from_response_object(acceptance_response)
            output_string = transaction_info['clean_string']
        if task_id_to_accept not in valid_task_ids_to_accept:
            print('task ID already accepted or not valid')
            output_string = 'task ID already accepted or not valid'
        return output_string

    def discord__task_refusal(self, seed_to_work, user_name, task_id_to_accept, refusal_string):
        """ EXAMPLE PARAMS
        seed_to_work = '___S'
        user_name = '.goodalexander'
        task_id_to_accept = '2024-08-17_17:57__TO94'
        refusal_string = "I will get this done as soon as I am able" 
        """ 
        wallet= self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=seed_to_work)
        wallet_address = wallet.classic_address
        all_wallet_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(wallet_address).copy()
        pf_df = self.generic_pft_utilities.convert_all_account_info_into_outstanding_task_df(account_memo_detail_df=all_wallet_transactions)
        valid_task_ids_to_refuse = list(pf_df[pf_df['acceptance']==''].index)

        if task_id_to_accept in valid_task_ids_to_refuse:
            print('valid task ID proceeding to refuse')
            formatted_refusal_string = 'REFUSAL REASON ___ '+refusal_string
            refusal_memo= self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=formatted_refusal_string, 
                                                                                                memo_format=user_name, memo_type=task_id_to_accept)
            refusal_response = self.generic_pft_utilities.send_PFT_with_info(sending_wallet=wallet, amount=1, memo=refusal_memo, destination_address=self.node_address)
            transaction_info = self.generic_pft_utilities.extract_transaction_info_from_response_object(refusal_response)
            output_string = transaction_info['clean_string']
        if task_id_to_accept not in valid_task_ids_to_refuse:
            print('task ID already accepted or not valid')
            output_string = 'task ID already accepted or not valid'
        return output_string

    def discord__initial_submission(self, seed_to_work, user_name, task_id_to_accept, initial_completion_string):
        """
        seed_to_work = ___
        user_name = '.goodalexander'
        task_id_to_accept = '2024-07-01_15:11__SR11'
        """ 
        wallet= self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=seed_to_work)
        wallet_address = wallet.classic_address
        all_wallet_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(wallet_address).copy()
        pf_df = self.generic_pft_utilities.convert_all_account_info_into_outstanding_task_df(account_memo_detail_df=all_wallet_transactions)

        valid_task_ids_to_submit_for_completion = list(pf_df[pf_df['acceptance']!=''].index)
        if task_id_to_accept in valid_task_ids_to_submit_for_completion:
            print('valid task ID proceeding to submit for completion')
            formatted_completed_justification_string = 'COMPLETION JUSTIFICATION ___ '+initial_completion_string
            completion_memo= self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=formatted_completed_justification_string, 
                                                                                                memo_format=user_name, memo_type=task_id_to_accept)
            completion_response = self.generic_pft_utilities.send_PFT_with_info(sending_wallet=wallet, amount=1, memo=completion_memo, destination_address=self.node_address)
            transaction_info = self.generic_pft_utilities.extract_transaction_info_from_response_object(completion_response)
            output_string = transaction_info['clean_string']
        if task_id_to_accept not in valid_task_ids_to_submit_for_completion:
            print('task ID has not been accepted or is not present')
            output_string = 'task ID has not been accepted or is not present'
        return output_string

    def discord__final_submission(self, seed_to_work, user_name, task_id_to_submit, justification_string):
        ''' 
        EXAMPLE PARAMETERS 
        seed_to_work='s___S'
        task_id_to_submit= '2024-08-19_20:04__RI89'
        user_name='.goodalexander'
        justification_string = """ I made sure that the xrpl link was displayed in the discord tool so that you could 
        go on to the explorer and get the data. the data is also cached to postgres. an example is quite literally this task which
        is being submitted for verification then processed, so it is ipso facto proof """
        ''' 
        wallet= self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=seed_to_work)
        wallet_address = wallet.classic_address
        all_wallet_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(wallet_address).copy()
        #outstanding_verification.tail(1)['memo_data'].unique()
        outstanding_verification = self.generic_pft_utilities.convert_all_account_info_into_outstanding_verification_df(account_memo_detail_df=all_wallet_transactions)
        valid_task_ids_to_submit_for_completion = list(outstanding_verification['memo_type'].unique())
        if task_id_to_submit in valid_task_ids_to_submit_for_completion:
            formatted_completed_justification_string = 'VERIFICATION RESPONSE ___ '+justification_string
            completion_memo= self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=formatted_completed_justification_string, 
                                                                                                            memo_format=user_name, memo_type=task_id_to_submit)
            completion_response = self.generic_pft_utilities.send_PFT_with_info(sending_wallet=wallet, amount=1, memo=completion_memo, destination_address=self.node_address)
            transaction_info = self.generic_pft_utilities.extract_transaction_info_from_response_object(completion_response)
            output_string = transaction_info['clean_string']
        if task_id_to_submit not in valid_task_ids_to_submit_for_completion:
            print('task ID is not a valid task for completion')
            output_string = 'task ID has not put into the verification cue'
        return output_string

    def process_outstanding_task_cue(self):
        """ This loads task requests processes them and sends the resulting workflows out""" 
        all_node_transactions = self.generic_pft_utilities.get_all_cached_transactions_related_to_account(self.node_address).copy()
        all_node_memo_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=self.node_address, 
                                                                                               pft_only=False).copy()
        postfiat_cue  = self.convert_all_node_memo_transactions_to_required_pft_generation(all_node_memo_transactions=all_node_memo_transactions).copy()
        pft_generation_to_work = postfiat_cue[postfiat_cue['requires_work']==True].copy()
        all_accounts= list(pft_generation_to_work['account'].unique())
        context_mapper = {}
        for xaccount in all_accounts:
            context_mapper[xaccount]=self.generic_pft_utilities.get_full_user_context_string(account_address=xaccount)
        pft_generation_to_work['full_user_context']=pft_generation_to_work['account'].map(context_mapper)
        if len(pft_generation_to_work)>0:  
            pft_generation_to_work['first_n_tasks_to_select']= pft_generation_to_work.apply(lambda x: self.phase_1_a__n_post_fiat_task_generator(full_user_context_replace=x['most_recent_status'], 
                                                                                              user_request=x['full_user_context'], n_copies=3),axis=1)
            pft_generation_to_work['task_string']=pft_generation_to_work['first_n_tasks_to_select'].apply(lambda x: x['n_task_output'])
            def convert_task_string_into_api_args(task_string_input, full_user_context_input):
                system_prompt = phase_1_b__system
                user_prompt = phase_1_b__user.replace('___SELECTION_OPTION_REPLACEMENT___', task_string_input).replace('___FULL_USER_CONTEXT_REPLACE___', full_user_context_input)
                api_args = {
                        "model": self.default_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ]}
                return api_args
            pft_generation_to_work['final_api_arg']=pft_generation_to_work.apply(lambda x: convert_task_string_into_api_args(task_string_input = x['task_string'],
                                                                                     full_user_context_input=x['full_user_context']),axis=1)
            selection_mapper = pft_generation_to_work.set_index('hash')['final_api_arg'].to_dict()
            async_df = self.openai_request_tool.create_writable_df_for_async_chat_completion(arg_async_map=selection_mapper)
            async_df['output_selection']=async_df['choices__message__content'].apply(lambda x: int(x.split('BEST OUTPUT |')[-1:][0].replace('|','').strip()))
            selected_choice = async_df.groupby('internal_name').first()['output_selection']
            pft_generation_to_work['best_choice']=pft_generation_to_work['hash'].map(selected_choice)
            pft_generation_to_work['df_to_extract']=pft_generation_to_work['first_n_tasks_to_select'].apply(lambda x: x['full_api_output'])
            pft_generation_to_work['task_string']=pft_generation_to_work['first_n_tasks_to_select'].apply(lambda x: x['n_task_output'])
            pft_generation_to_work['best_choice_string']= pft_generation_to_work['best_choice'].apply(lambda x: 'OUTPUT '+str(x))
            def get_output_map_for_output_value(choice_string, df_to_extract):
            #choice_string = 'OUTPUT 3'    
                output_map = {}
                selection_df = df_to_extract[df_to_extract['classification']==choice_string]
                simple_string = list(selection_df['simplified_string'])[0]
                simple_reward = float(list(selection_df['value'])[0])
                output_map ={'task': simple_string, 'reward': simple_reward}
                return output_map
            pft_generation_to_work['task_map']=pft_generation_to_work.apply(lambda x: get_output_map_for_output_value(x['best_choice_string'],x['df_to_extract']), axis=1)
            pft_generation_to_work['task_string_to_send']='PROPOSED PF ___ '+ pft_generation_to_work['task_map'].apply(lambda x: x['task'])
            pft_generation_to_work['memo_to_send']= pft_generation_to_work.apply(lambda x: self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=x['task_string_to_send'], 
                                                                                                               memo_format=x['memo_format'], 
                                                                                                               memo_type=x['memo_type']),axis=1)
            rows_to_work = list(pft_generation_to_work.index)
        
            for xrow in rows_to_work:
                slicex = pft_generation_to_work.loc[xrow]
                memo_to_send=slicex.loc['memo_to_send']
                pft_user_account = slicex.loc['user_account']
                destination_address = slicex.loc['user_account']
                node_wallet = self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=self.node_seed)
                self.generic_pft_utilities.send_PFT_with_info(sending_wallet=node_wallet, amount=1, 
                                                              memo=memo_to_send, destination_address=destination_address)

    def process_verification_cue(self):
        all_node_memo_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=self.node_address, 
                                                                                            pft_only=False).copy().sort_values('datetime')
        all_completions = all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: 
                                                                                'COMPLETION JUSTIFICATION' in x)].copy()
        most_recent_task_update = all_node_memo_transactions[['memo_data','memo_type']].groupby('memo_type').last()['memo_data']
        all_completions['recent_update']=all_completions['memo_type'].map(most_recent_task_update )
        all_completions['requires_work']=all_completions['recent_update'].apply(lambda x: 'COMPLETION JUSTIFICATION' in x)
        original_task_description = all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: ('PROPOSED PF' in x)
                                                                                |('..' in x))][['memo_data','memo_type']].groupby('memo_type').last()['memo_data']
        verification_prompts_to_disperse = all_completions[all_completions['requires_work']==True].copy()
        verification_prompts_to_disperse['original_task']=verification_prompts_to_disperse['memo_type'].map(original_task_description )
        def construct_api_arg_for_verification(original_task, completion_justification):
            user_prompt = verification_user_prompt.replace('___COMPLETION_STRING_REPLACEMENT_STRING___',completion_justification)
            user_prompt=user_prompt.replace('___TASK_REQUEST_REPLACEMENT_STRING___',original_task)
            system_prompt= verification_system_prompt
            api_args = {
                                "model": self.default_model,
                                "messages": [
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}
                                ]}
            return api_args
        if len(verification_prompts_to_disperse)>0:
            verification_prompts_to_disperse['api_args']=verification_prompts_to_disperse.apply(lambda x: construct_api_arg_for_verification(x['original_task'], x['memo_data']),axis=1)
            async_df = self.openai_request_tool.create_writable_df_for_async_chat_completion(verification_prompts_to_disperse.set_index('hash')['api_args'].to_dict())
            hash_to_internal_name = async_df[['choices__message__content','internal_name']].groupby('internal_name').last()['choices__message__content']
            verification_prompts_to_disperse['raw_output']=verification_prompts_to_disperse['hash'].map(hash_to_internal_name)
            verification_prompts_to_disperse['stripped_question']=verification_prompts_to_disperse['raw_output'].apply(lambda x: 
                                                                                                                    x.split('Verifying Question |')[-1:][0].replace('|','').strip())
            verification_prompts_to_disperse['verification_string_to_send']='VERIFICATION PROMPT ___ '+ verification_prompts_to_disperse['stripped_question']
            verification_prompts_to_disperse['memo_to_send']= verification_prompts_to_disperse.apply(lambda x: self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=x['verification_string_to_send'], 
                                                                                                                        memo_format=x['memo_format'], 
                                                                                                                        memo_type=x['memo_type']),axis=1)
            rows_to_work = list(verification_prompts_to_disperse.index)
                    
            for xrow in rows_to_work:
                slicex = verification_prompts_to_disperse.loc[xrow]
                memo_to_send=slicex.loc['memo_to_send']
                pft_user_account = slicex.loc['user_account']
                destination_address = slicex.loc['user_account']
                node_wallet = self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=self.node_seed)
                self.generic_pft_utilities.send_PFT_with_info(sending_wallet=node_wallet, amount=1, 
                                                            memo=memo_to_send, destination_address=destination_address)


    def process_full_final_reward_cue(self):
        all_node_memo_transactions = self.generic_pft_utilities.get_memo_detail_df_for_account(account_address=self.node_address, 
                                                                                            pft_only=False).copy().sort_values('datetime')
        all_completions = all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: 
                                                                                'VERIFICATION RESPONSE ___' in x)].copy()
        
        recent_rewards = all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: 
                                                                                'REWARD RESPONSE' in x)].copy()
        reward_summary_frame = recent_rewards[recent_rewards['datetime']>=datetime.datetime.now()-datetime.timedelta(35)][['account','memo_data','directional_pft',
                                                                                                                        'destination']].copy()
        reward_summary_frame['full_string']=reward_summary_frame['memo_data']+" REWARD "+ (reward_summary_frame['directional_pft']*-1).astype(str)
        reward_history_map = reward_summary_frame.groupby('destination')[['full_string']].sum()['full_string']
        most_recent_task_update = all_node_memo_transactions[['memo_data','memo_type']].groupby('memo_type').last()['memo_data']
        all_completions['recent_update']=all_completions['memo_type'].map(most_recent_task_update )
        all_completions['requires_work']=all_completions['recent_update'].apply(lambda x: 'VERIFICATION RESPONSE ___' in x)
        reward_cue = all_completions[all_completions['requires_work'] == True].copy()[['memo_type','memo_format',
                                                                        'memo_data','datetime','account','hash']].groupby('memo_type').last().sort_values('datetime').copy()
        account_to_google_context_map = all_node_memo_transactions[all_node_memo_transactions['memo_type']=='google_doc_context_link'].groupby('account').last()['memo_data']
        unique_accounts = list(reward_cue['account'].unique())
        google_context_memo_map ={}
        for xaccount in unique_accounts :
            raw_text = self.generic_pft_utilities.get_google_doc_text(share_link=account_to_google_context_map[xaccount])
            verification = raw_text.split('VERIFICATION SECTION START')[-1:][0].split('VERIFICATION SECTION END')[0]
            google_context_memo_map[xaccount] = verification
        reward_cue['google_verification_details']= reward_cue['account'].map(google_context_memo_map).fillna('No Populated Verification Section')
        task_id_to__initial_task = all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: 
                                                                                ('PROPOSED' in x) | ('..' in x))].groupby('memo_type').first()['memo_data']
        
        task_id_to__verification_prompt= all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: 
                                                                                ('VERIFICATION PROMPT' in x))].groupby('memo_type').first()['memo_data']
        task_id_to__verification_response= all_node_memo_transactions[all_node_memo_transactions['memo_data'].apply(lambda x: 
                                                                                ('VERIFICATION RESPONSE' in x))].groupby('memo_type').first()['memo_data']
        
        if len(reward_cue)>0:
            reward_cue['initial_task']= task_id_to__initial_task
            reward_cue['verification_prompt']= task_id_to__verification_prompt
            reward_cue['verification_response']= task_id_to__verification_response
            reward_cue['reward_history']=reward_cue['account'].map(reward_history_map)
            reward_cue['proposed_reward'] =reward_cue['initial_task'].fillna('').apply(lambda x: x.split('..')[-1:][0])
            reward_cue['system_prompt']=reward_cue['proposed_reward'].apply(lambda x: reward_system_prompt.replace('___PROPOSED_REWARD_REPLACEMENT___',x))
            reward_cue['user_prompt']=reward_user_prompt
            reward_cue['initial_task']= reward_cue['initial_task'].fillna('')
            reward_cue['verification_prompt']= reward_cue['verification_prompt'].fillna('')
            reward_cue['reward_history']= reward_cue['reward_history'].fillna('')
        
            def augment_user_prompt_with_key_attributes(
                sample_user_prompt,
                task_proposal_replacement,
                verification_question_replacement,
                verification_answer_replacement,
                verification_details_replacement,
                reward_details_replacement,
                proposed_reward_replacement
            ):
                """
                Augment a user prompt with key attributes by replacing placeholder strings.
            
                Args:
                sample_user_prompt (str): The original user prompt with placeholder strings.
                task_proposal_replacement (str): The task proposal to replace the placeholder.
                verification_question_replacement (str): The verification question to replace the placeholder.
                verification_answer_replacement (str): The verification answer to replace the placeholder.
                verification_details_replacement (str): The verification details to replace the placeholder.
                reward_details_replacement (str): The reward details to replace the placeholder.
            
                Returns:
                str: The augmented user prompt with placeholders replaced by actual values.
                """
                # Replace placeholders with actual values
                augmented_prompt = sample_user_prompt.replace('___TASK_PROPOSAL_REPLACEMENT___', task_proposal_replacement)
                augmented_prompt = augmented_prompt.replace('___VERIFICATION_QUESTION_REPLACEMENT___', verification_question_replacement)
                augmented_prompt = augmented_prompt.replace('___TASK_VERIFICATION_REPLACEMENT___', verification_answer_replacement)
                augmented_prompt = augmented_prompt.replace('___VERIFICATION_DETAILS_REPLACEMENT___', verification_details_replacement)
                augmented_prompt = augmented_prompt.replace('___ REWARD_DATA_REPLACEMENT ___', reward_details_replacement)
                augmented_prompt = augmented_prompt.replace('___PROPOSED_REWARD_REPLACEMENT___', proposed_reward_replacement)
            
                return augmented_prompt
            
            reward_cue['augmented_user_prompt'] = reward_cue.apply(
                lambda row: augment_user_prompt_with_key_attributes(
                    sample_user_prompt=row['user_prompt'],
                    task_proposal_replacement=row['initial_task'],
                    verification_question_replacement=row['verification_prompt'],
                    verification_answer_replacement=row['verification_response'],
                    verification_details_replacement=row['google_verification_details'],
                    reward_details_replacement=row['reward_history'],
                    proposed_reward_replacement=row['proposed_reward']
                ),
                axis=1
            )
            def create_reward_api_args(user_prompt, system_prompt):
                api_args = {
                            "model": self.default_model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ]
                        }
                return api_args
            
            reward_cue['api_arg']=reward_cue.apply(lambda x: create_reward_api_args(x['augmented_user_prompt'],x['system_prompt']),axis=1)
            async_df = self.openai_request_tool.create_writable_df_for_async_chat_completion(arg_async_map=reward_cue.set_index('hash')['api_arg'].to_dict())
            hash_to_choices_message_content = async_df.groupby('internal_name').first()['choices__message__content']
            reward_cue['full_reward_string']=reward_cue['hash'].map(hash_to_choices_message_content)
            def extract_pft_reward(x):
                ret = 1
                try:
                    ret = np.abs(int(x.split('| Total PFT Rewarded |')[-1:][0].replace('|','').strip()))
                except:
                    pass
                return ret
            
            def extract_summary_judgement(x):
                ret = 'Summary Judgment'
                try:
                    ret = x.split('| Summary Judgment |')[-1:][0].split('|')[0].strip()
                except:
                    pass
                return ret
            
            reward_cue['reward_to_dispatch']=reward_cue['full_reward_string'].apply(lambda x: extract_pft_reward(x))
            reward_cue['reward_summary']='REWARD RESPONSE __ ' +reward_cue['full_reward_string'].apply(lambda x: extract_summary_judgement(x))
            reward_dispatch=reward_cue.reset_index()
            reward_dispatch['memo_to_send']= reward_dispatch.apply(lambda x: self.generic_pft_utilities.construct_standardized_xrpl_memo(memo_data=x['reward_summary'], 
                                                                                                                                memo_format=x['memo_format'], 
                                                                                                                                memo_type=x['memo_type']),axis=1)
            rows_to_work = list(reward_dispatch.index)
            for xrow in rows_to_work:
                slicex = reward_dispatch.loc[xrow]
                memo_to_send=slicex.loc['memo_to_send']
                print(memo_to_send)
                destination_address = slicex.loc['account']
                reward_to_dispatch = int(np.abs(slicex.loc['reward_to_dispatch']))
                reward_to_dispatch = int(np.min([reward_to_dispatch,1200]))
                reward_to_dispatch = int(np.max([reward_to_dispatch,1]))
                node_wallet = self.generic_pft_utilities.spawn_user_wallet_from_seed(seed=self.node_seed)
                self.generic_pft_utilities.send_PFT_with_info(sending_wallet=node_wallet, amount=reward_to_dispatch, 
                                                            memo=memo_to_send, destination_address=destination_address)

    def server_loop(self):
        total_time_to_run=1_000_000_000
        i=0
        while i<total_time_to_run:
            self.generic_pft_utilities.write_all_postfiat_holder_transaction_history(public=False)
            time.sleep(1)
            try:
                self.process_outstanding_task_cue()
                self.generic_pft_utilities.write_all_postfiat_holder_transaction_history(public=False)
                    # Process initiation rewards
            except:
                pass
            try:
                self.node_cue_function__initiation_rewards()
            except:
                pass
            try:        
                self.generic_pft_utilities.write_all_postfiat_holder_transaction_history(public=False)
                    # Process final rewards
                self.process_full_final_reward_cue()
            except:
                pass

            try:                
                self.generic_pft_utilities.write_all_postfiat_holder_transaction_history(public=False)
                    # Process verifications
                self.process_verification_cue()
                self.generic_pft_utilities.write_all_postfiat_holder_transaction_history(public=False)
            except:
                pass
            i=i+1
            time.sleep(1)
    
    def run_cue_processing(self):
        """
        Runs cue processing tasks sequentially in a single thread.
        Each task runs to completion before starting again.
        """
        self.stop_threads = False

        def process_all_tasks():
            while not self.stop_threads:
                # Process outstanding tasks
                try:
                    self.process_outstanding_task_cue()
                except:
                    pass
                # Process initiation rewards
                self.node_cue_function__initiation_rewards()

                # Process final rewards
                self.process_full_final_reward_cue()

                # Process verifications
                self.process_verification_cue()

                # Short delay before checking if we should continue
                time.sleep(1)  # 1 second delay

        # Create and start a single thread
        self.processing_thread = threading.Thread(target=process_all_tasks)
        self.processing_thread.daemon = True
        self.processing_thread.start()

    def stop_cue_processing(self):
        """
        Stops the cue processing thread.
        """
        self.stop_threads = True
        if hasattr(self, 'processing_thread'):
            self.processing_thread.join(timeout=60)  # W

    def write_full_initial_discord_chat_history(self):
        """ Write the full transaction set """ 
        simplified_message_df =self.generic_pft_utilities.get_memo_detail_df_for_account(account_address
                                                                =self.generic_pft_utilities.node_address).sort_values('datetime')
        simplified_message_df['url']=simplified_message_df['hash'].apply(lambda x: f'https://livenet.xrpl.org/transactions/{x}/detailed')

        def format_message(row):
            """
            Format a message string from the given row of simplified_message_df.
            
            Args:
            row (pd.Series): A row from simplified_message_df containing the required fields.
            
            Returns:
            str: Formatted message string.
            """
            return (f"Date: {row['datetime']}\n"
                    f"Account: {row['account']}\n"
                    f"Memo Format: {row['memo_format']}\n"
                    f"Memo Type: {row['memo_type']}\n"
                    f"Memo Data: {row['memo_data']}\n"
                    f"Directional PFT: {row['directional_pft']}\n"
                    f"URL: {row['url']}")

        # Apply the function to create a new 'formatted_message' column
        simplified_message_df['formatted_message'] = simplified_message_df.apply(format_message, axis=1)
        full_history = simplified_message_df[['datetime','account','memo_format',
                            'memo_type','memo_data','directional_pft','url','hash','formatted_message']].copy()
        full_history['displayed']=True
        dbconnx = self.db_connection_manager.spawn_sqlalchemy_db_connection_for_user(user_name=self.generic_pft_utilities.node_name)
        full_history.to_sql('foundation_discord', dbconnx, if_exists='replace')

    def output_messages_to_send_and_write_incremental_info_to_foundation_discord_db(self):
        dbconnx = self.db_connection_manager.spawn_sqlalchemy_db_connection_for_user(user_name=self.generic_pft_utilities.node_name)
        existing_hashes = list(pd.read_sql('select hash from foundation_discord', dbconnx)['hash'])
        dbconnx.dispose()
        simplified_message_df =self.generic_pft_utilities.get_memo_detail_df_for_account(account_address
                                                                =self.generic_pft_utilities.node_address).sort_values('datetime')
        simplified_message_df['url']=simplified_message_df['hash'].apply(lambda x: f'https://livenet.xrpl.org/transactions/{x}/detailed')
        
        def format_message(row):
            """
            Format a message string from the given row of simplified_message_df.
            
            Args:
            row (pd.Series): A row from simplified_message_df containing the required fields.
            
            Returns:
            str: Formatted message string.
            """
            return (f"Date: {row['datetime']}\n"
                    f"Account: {row['account']}\n"
                    f"Memo Format: {row['memo_format']}\n"
                    f"Memo Type: {row['memo_type']}\n"
                    f"Memo Data: {row['memo_data']}\n"
                    f"Directional PFT: {row['directional_pft']}\n"
                    f"URL: {row['url']}")
        
        # Apply the function to create a new 'formatted_message' column
        simplified_message_df['formatted_message'] = simplified_message_df.apply(format_message, axis=1)
        simplified_message_df.set_index('hash',inplace=True)
        incremental_df = simplified_message_df[simplified_message_df.index.isin(existing_hashes) == False]
        messages_to_send = list(incremental_df['formatted_message'])
        writer_df = incremental_df.reset_index()

        if len(writer_df)>0:
            dbconnx = self.db_connection_manager.spawn_sqlalchemy_db_connection_for_user(user_name=self.generic_pft_utilities.node_name)
            writer_df[['hash','memo_data','memo_type','memo_format','datetime','url','directional_pft','account']].to_sql('foundation_discord', 
                                                                                                                        dbconnx, if_exists='append')
            dbconnx.dispose()
        return messages_to_send
