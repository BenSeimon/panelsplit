from sklearn.model_selection import TimeSeriesSplit
from tqdm import tqdm
import pandas as pd
import matplotlib.pyplot as plt
from joblib import Parallel, delayed
import numpy as np

class PanelSplit:
    def __init__(self, train_periods, unique_periods= None, n_splits = 5, gap = None, test_size = None, max_train_size=None, plot=False, drop_folds=False, y=None):
        """
        A class for performing time series cross-validation with custom train/test splits based on unique periods.

        Parameters:
        - train_periods: All available training periods
        - unique_periods: Pandas DataFrame or Series containing unique periods. 
        - n_splits: Number of splits for TimeSeriesSplit
        - gap: Gap between train and test sets in TimeSeriesSplit
        - test_size: Size of the test set in TimeSeriesSplit
        - max_train_size: Maximum size for a single training set.
        - plot: Flag to visualize time series splits
        """

        if unique_periods == None:
            unique_periods = pd.Series(train_periods.unique()).sort_values()
        self.tss = TimeSeriesSplit(n_splits=n_splits, gap=gap, test_size=test_size, max_train_size = max_train_size)
        indices = self.tss.split(unique_periods.reset_index(drop=True))
        self.u_periods_cv = self.split_unique_periods(indices, unique_periods)
        self.all_periods = train_periods
    
        if y is not None and drop_folds is False:
            warnings.warn("Ignoring y values because drop_folds is False.")
        
        if y is None and drop_folds is True:
            raise ValueError("Cannot drop folds without specifying y values.")
        
        self.drop_folds = drop_folds

        self.n_splits = n_splits
        self.split(y=y, init=True)

        if plot:
            self.plot_time_series_splits(self.u_periods_cv)
        
    def split_unique_periods(self, indices, unique_periods):
        """
        Split unique periods into train/test sets based on TimeSeriesSplit indices.

        Parameters:
        - indices: TimeSeriesSplit indices
        - unique_periods: Pandas DataFrame or Series containing unique periods

        Returns: List of tuples containing train and test periods
        """
        u_periods_cv = []
        for i, (train_index, test_index) in enumerate(indices):
            unique_train_periods = unique_periods.iloc[train_index].values
            unique_test_periods = unique_periods.iloc[test_index].values
            u_periods_cv.append((unique_train_periods, unique_test_periods))
        return u_periods_cv

    def split(self, X = None, y = None, groups=None, init=False):
        """
        Generate train/test indices based on unique periods.
        """
        self.all_indices = []
        
        for i, (train_periods, test_periods) in enumerate(self.u_periods_cv):
            train_indices = self.all_periods.isin(train_periods).values
            test_indices = self.all_periods.isin(test_periods).values
            
            if self.drop_folds and ((len(train_indices) == 0 or len(test_indices) == 0) or (y.loc[train_indices].nunique() == 1 or y.loc[test_indices].nunique() == 1)):
                if init:
                    self.n_splits -= 1
                    print(f'Dropping fold {i} as either the test or train set is either empty or contains only one unique value.')
                else:
                    continue
            else:
                self.all_indices.append((train_indices, test_indices))
        
        return self.all_indices
   
    def get_n_splits(self, X=None, y =None, groups=None):
        """
        Returns: Number of splits
        """
        return self.n_splits
    
    def _predict_fold(self, estimator, X_train, y_train, X_test, prediction_method='predict', sample_weight=None):
        """
        Perform predictions for a single fold.

        Parameters:
        -----------
        estimator : The machine learning model used for prediction.

        X_train : pandas DataFrame
            The input features for training.

        y_train : pandas Series
            The target variable for training.

        X_test : pandas DataFrame
            The input features for testing.

        prediction_method : str, optional (default='predict')
            The prediction method to use. It can be 'predict', 'predict_proba', or 'predict_log_proba'.

        sample_weight : pandas Series or numpy array, optional (default=None)
            Sample weights for the training data.

        Returns:
        --------
        pd.Series
            Series containing predicted values.

        """
        model = estimator.fit(X_train, y_train, sample_weight=sample_weight)

        if prediction_method == 'predict':
            return model.predict(X_test), model
        elif prediction_method == 'predict_proba':
            return model.predict_proba(X_test)[:, 1], model
        elif prediction_method == 'predict_log_proba':
            return model.predict_log_proba(X_test)[:, 1], model
        else:
            raise ValueError("Invalid prediction_method. Supported values are 'predict', 'predict_proba', or 'predict_log_proba'.")

    def cross_val_predict(self, estimator, X, y, indices, prediction_method='predict', y_pred_col=None,
                          return_fitted_models=False, sample_weight=None):
        """
        Perform cross-validated predictions using a given predictor model.

        Parameters:
        -----------
        estimator : The machine learning model used for prediction.

        X : pandas DataFrame
            The input features for the predictor.

        y : pandas Series
            The target variable to be predicted.

        indices : pandas DataFrame
            Indices corresponding to the dataset.

        prediction_method : str, optional (default='predict')
            The prediction method to use. It can be 'predict', 'predict_proba', or 'predict_log_proba'.

        y_pred_col : str, optional (default=None)
            The column name for the predicted values.

        return_fitted_models : bool, optional (default=False)
            If True, return a list of fitted models at the end of cross-validation.

        sample_weight : pandas Series or numpy array, optional (default=None)
            Sample weights for the training data.

        Returns:
        --------
        pd.DataFrame
            Concatenated DataFrame containing predictions made by the model during cross-validation.
            It includes the original indices joined with the predicted values.

        list of fitted models (if return_fitted_models=True)
            List containing fitted models for each fold.

        """
        predictions = []
        fitted_models = []  # List to store fitted models
        if y_pred_col is None:
            if hasattr(y, 'name'):
                y_pred_col = str(y.name) + '_pred'
            else:
                y_pred_col =  'y_pred'

        for train_indices, test_indices in tqdm(self.split()):
            # first drop nas with respect to y_train
            y_train = y.loc[train_indices].dropna()
            # use y_train to filter for X_train
            X_train = X.loc[y_train.index]
            X_test, _ = X.loc[test_indices], y.loc[test_indices]
            pred = indices.loc[test_indices].copy()

            if sample_weight is not None:
                pred[y_pred_col], model = self._predict_fold(estimator, X_train, y_train, X_test, prediction_method, sample_weight=sample_weight[y_train.index])
            else:
                pred[y_pred_col], model = self._predict_fold(estimator, X_train, y_train, X_test, prediction_method)

            fitted_models.append(model)  # Store the fitted model

            predictions.append(pred)

        result_df = pd.concat(predictions, axis=0)

        if return_fitted_models:
            return result_df, fitted_models
        else:
            return result_df
    
    def plot_time_series_splits(self, split_output):
        """
        Visualize time series splits using a scatter plot.

        Parameters:
        - split_output: Output of time series splits
        """
        folds = len(split_output)
        fig, ax = plt.subplots()
        
        for i, (train_index, test_index) in enumerate(split_output):
            ax.scatter(train_index, [i] * len(train_index), color='blue', marker='.', s=50)
            ax.scatter(test_index, [i] * len(test_index), color='red', marker='.', s=50)

        ax.set_xlabel('Periods')
        ax.set_ylabel('Folds')
        ax.set_title('Cross-Validation Splits')
        ax.set_yticks(range(folds))  # Set the number of ticks on y-axis
        ax.set_yticklabels([f'{i}' for i in range(folds)])  # Set custom labels for y-axi
        plt.show()

    def cross_val_impute(self, imputer, X, return_fitted_imputers=False):
         
        """
        Perform cross-validated imputation using a given imputer.
    
        Parameters:
        -----------
        imputer : The imputer object used for imputation.
    
        X : pandas DataFrame
            The input features for the imputer.
    
        Returns:
        --------
        np.ndarray
            Concatenated array containing imputed values during cross-validation.
        """
        imputed_values = []
        imputers = []
    
        splits = self.split()
        _X = X.copy()
    
        for train_indices, test_indices in tqdm(self.split()):
            X_train = _X.loc[train_indices]
            X_test = _X.loc[test_indices]
    
            # Fit the imputer on the train set and transform the test set
            imputer_train = clone(imputer)
            imputer_train.fit(X_train)
            imputers.append(imputer_train)
    
            _X.loc[test_indices] = imputer_train.transform(X_test)
    
        if return_fitted_imputers:
            return _X, imputers
        else:
            return _X
